"""Real PDF extraction and HTTP intake limits, without any model calls."""
import base64
import hashlib
from http.client import HTTPConnection
import io
import json
import subprocess
import threading
import unittest
from unittest.mock import patch

from backend.documents import DocumentError, MAX_FILE_BYTES, extract_document
from server import Handler, ThreadingHTTPServer
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def make_text_pdf(pages):
    """Return a real ASCII text PDF; a None page models a scan with no text layer."""
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference}),
        })
        commands = ["BT /F1 12 Tf 40 750 Td 16 TL"]
        for index, line in enumerate(text.splitlines()):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(("T* " if index else "") + f"({escaped}) Tj")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def encoded(raw):
    return base64.b64encode(raw).decode("ascii")


class DocumentTests(unittest.TestCase):
    def test_actual_pdf_extraction_preserves_pages_and_fingerprint(self):
        raw = make_text_pdf(["Project: Campus travel\nDeliver: report.md", "Analyze survey results and prepare summary.csv"])
        document = extract_document("requirements.PDF", encoded(raw))
        self.assertEqual(document["source_type"], "pdf")
        self.assertEqual(document["page_count"], 2)
        self.assertEqual(document["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIn("Campus travel", document["pages"][0]["text"])
        self.assertIn("summary.csv", document["pages"][1]["text"])
        self.assertIn("[Page 1]", document["text"])
        self.assertIn("[Page 2]", document["text"])
        self.assertEqual(document["warnings"], [])

    def test_mixed_pdf_reports_missing_text_page(self):
        document = extract_document("mixed.pdf", encoded(make_text_pdf(["Read the requirements", None, "Write report.md"])))
        self.assertEqual(document["page_count"], 3)
        self.assertEqual(document["pages"][1], {"number": 2, "text": ""})
        self.assertEqual(len(document["warnings"]), 1)
        self.assertIn("第 2 页", document["warnings"][0])
        self.assertIn("[Page 3]", document["text"])

    def test_scan_without_text_explains_ocr_limit(self):
        with self.assertRaises(DocumentError) as error:
            extract_document("scan.pdf", encoded(make_text_pdf([None])))
        self.assertEqual(error.exception.status, 422)
        self.assertIn("OCR", str(error.exception))

    def test_corrupt_pdf_gives_safe_error_without_parser_contents(self):
        for raw in (b"not-a-pdf", b"%PDF-1.7\nprivate-document-parser-data"):
            with self.subTest(raw=raw[:8]), self.assertRaises(DocumentError) as error:
                extract_document("corrupt.pdf", encoded(raw))
            self.assertNotIn("private-document-parser-data", str(error.exception))

    def test_encrypted_pdf_is_explicitly_rejected(self):
        writer = PdfWriter()
        writer.append_pages_from_reader(PdfReader(io.BytesIO(make_text_pdf(["Confidential requirements"]))))
        writer.encrypt("test-fixture-password")
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaises(DocumentError) as error:
            extract_document("locked.pdf", encoded(output.getvalue()))
        self.assertIn("加密", str(error.exception))

    def test_page_limit_rejects_whole_document(self):
        with self.assertRaises(DocumentError) as error:
            extract_document("long.pdf", encoded(make_text_pdf(["Task"] * 41)))
        self.assertEqual(error.exception.status, 413)
        self.assertIn("40", str(error.exception))

    def test_text_limits_do_not_silently_truncate(self):
        raw = make_text_pdf(["A" * 60_001])
        for filename, content in (("long.pdf", raw), ("long.txt", b"A" * 60_001)):
            with self.subTest(filename=filename), self.assertRaises(DocumentError) as error:
                extract_document(filename, encoded(content))
            self.assertEqual(error.exception.status, 413)
            self.assertIn("60,000", str(error.exception))

    def test_upload_size_limit_is_checked_before_worker(self):
        with patch("backend.documents._extract_pdf_subprocess") as worker:
            with self.assertRaises(DocumentError) as error:
                extract_document("large.pdf", encoded(b"%PDF-" + b"x" * MAX_FILE_BYTES))
        worker.assert_not_called()
        self.assertEqual(error.exception.status, 413)

    def test_strict_base64_and_file_types(self):
        for value in (None, 123, "", "%%%%", "YWJj\n", "data:text/plain;base64,YWJj", "非ASCII"):
            with self.subTest(value=value), self.assertRaises(DocumentError):
                extract_document("brief.txt", value)
        for name in ("", None, "../brief.txt", "C:\\brief.txt", "bad\x00.txt", "brief.exe"):
            with self.subTest(name=name), self.assertRaises(DocumentError):
                extract_document(name, encoded(b"Goal: build a report"))

    def test_utf8_markdown_and_text(self):
        raw = "\ufeff# 项目需求\r\n调研校园出行，交付报告。".encode("utf-8")
        for extension in ("md", "txt"):
            document = extract_document(f"需求.{extension}", encoded(raw))
            self.assertEqual(document["text"], "# 项目需求\n调研校园出行，交付报告。")
            self.assertEqual(document["source_type"], "text")
            self.assertEqual(document["pages"], [{"number": 1, "text": document["text"]}])
        for raw in (b"\xff\xfe", b"\x00binary", b" \n "):
            with self.subTest(raw=raw), self.assertRaises(DocumentError):
                extract_document("brief.txt", encoded(raw))

    def test_decompression_bomb_is_bounded(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(b" " * (9 * 1024 * 1024))
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
        output = io.BytesIO()
        writer.write(output)
        self.assertLess(len(output.getvalue()), MAX_FILE_BYTES)
        with self.assertRaises(DocumentError) as error:
            extract_document("compressed.pdf", encoded(output.getvalue()))
        self.assertEqual(error.exception.status, 413)

    def test_hard_timeout_gives_actionable_error(self):
        with patch("backend.documents.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 20)):
            with self.assertRaises(DocumentError) as error:
                extract_document("slow.pdf", encoded(b"%PDF-test"))
        self.assertEqual(error.exception.status, 422)
        self.assertIn("20 秒", str(error.exception))

    def test_worker_does_not_receive_model_credentials(self):
        result = {"page_count": 1, "text": "Requirements", "pages": [{"number": 1, "text": "Requirements"}], "warnings": []}
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(result).encode())
        with patch.dict("os.environ", {"OPENAI_API_KEY": "private-fixture-key", "OTHER_PROVIDER_SECRET": "another-private-key"}):
            with patch("backend.documents.subprocess.run", return_value=completed) as run:
                extract_document("safe.pdf", encoded(b"%PDF-test"))
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("OTHER_PROVIDER_SECRET", environment)


class DocumentHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, path, body, origin=None, content_length=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=30)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        try:
            connection.request("POST", path, json.dumps(body).encode("utf-8"), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_actual_extract_route(self):
        status, response = self.post("/api/requirements/extract", {"filename": "brief.pdf", "content_base64": encoded(make_text_pdf(["Prepare a report"]))})
        self.assertEqual(status, 200, response)
        self.assertIn("Prepare a report", response["document"]["text"])

    def test_extract_route_keeps_same_origin_protection(self):
        status, _ = self.post("/api/requirements/extract", {"filename": "brief.txt", "content_base64": encoded(b"Requirements")}, "https://outside.example")
        self.assertEqual(status, 403)

    def test_analysis_route_forwards_the_document_and_planner(self):
        document = extract_document("brief.txt", encoded(b"Analyze campus travel and deliver report.md"))
        planner = {"provider": "openai", "model": "fixture-model", "credential_ref": "OPENAI_API_KEY"}
        analysis = {"project_name": "Travel", "goal": "Analyze campus travel", "tasks": [], "deliverables": ["report.md"], "constraints": [], "missing_information": []}
        with patch("backend.requirements.analyze_requirements", return_value=analysis) as analyze:
            status, response = self.post("/api/requirements/analyze", {"document": document, "planner": planner})
        self.assertEqual(status, 200, response)
        self.assertEqual(response, {"analysis": analysis})
        analyze.assert_called_once_with(document, planner)

    def test_invalid_analysis_document_returns_safe_validation_error(self):
        status, response = self.post("/api/requirements/analyze", {"document": {}, "planner": {}})
        self.assertEqual(status, 400, response)
        self.assertIn("需求文档", response["error"])

    def test_extract_has_8_mib_body_limit_and_other_routes_keep_4_mib(self):
        status, response = self.post("/api/requirements/extract", {}, content_length=8 * 1024 * 1024 + 1)
        self.assertEqual(status, 413)
        self.assertIn("8 MiB", response["error"])
        status, response = self.post("/api/requirements/analyze", {}, content_length=4 * 1024 * 1024 + 1)
        self.assertEqual(status, 413)
        self.assertIn("4 MiB", response["error"])

    def test_larger_extract_body_reaches_file_limit_validation(self):
        # A base64 body can exceed the old 4 MiB HTTP cap while the file is below 5 MiB.
        status, response = self.post("/api/requirements/extract", {"filename": "large.txt", "content_base64": encoded(b"A" * (3 * 1024 * 1024 + 1))})
        self.assertEqual(status, 413)
        self.assertIn("60,000", response["error"])


if __name__ == "__main__":
    unittest.main()
