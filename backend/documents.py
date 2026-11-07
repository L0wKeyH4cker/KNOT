"""Bounded local extraction of uploaded requirement documents; originals stay in memory."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PAGES = 40
MAX_TEXT_CHARACTERS = 60_000
PDF_TIMEOUT_SECONDS = 20
MAX_STREAM_BYTES = 8 * 1024 * 1024
MAX_TOTAL_STREAM_BYTES = 20 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


class DocumentError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _check_text_limit(text):
    if len(text) > MAX_TEXT_CHARACTERS:
        raise DocumentError("提取的文字超过 60,000 字符。请拆分文件后再上传，不会自动截断内容。", 413)


def extract_document(filename, content_base64):
    """Accept a strictly encoded upload and return text with source page provenance."""
    if not isinstance(filename, str) or not filename.strip():
        raise DocumentError("请选择一个有文件名的需求文档。")
    filename = filename.strip()
    if len(filename) > 240 or any(ord(char) < 32 or char in "/\\" for char in filename):
        raise DocumentError("文件名无效，请使用普通文件名重新上传。")
    extension = Path(filename).suffix.lower()
    if extension not in (".pdf", ".txt", ".md"):
        raise DocumentError("支持 PDF、TXT 和 Markdown 文件。", 415)
    if not isinstance(content_base64, str) or not content_base64:
        raise DocumentError("文件为空，请选择包含项目需求的文件。")
    if len(content_base64) > 4 * ((MAX_FILE_BYTES + 2) // 3):
        raise DocumentError("文件超过 5 MiB，请拆分或压缩后再上传。", 413)
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise DocumentError("文件编码无效，请重新选择并上传文件。") from None
    if not raw:
        raise DocumentError("文件为空，请选择包含项目需求的文件。")
    if len(raw) > MAX_FILE_BYTES:
        raise DocumentError("文件超过 5 MiB，请拆分或压缩后再上传。", 413)
    if extension == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise DocumentError("这不是有效的 PDF 文件，请重新导出 PDF 后上传。")
        result = _extract_pdf_subprocess(raw)
        source_type = "pdf"
    else:
        try:
            text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
        except UnicodeError:
            raise DocumentError("文本文件必须使用 UTF-8 编码，请另存为 UTF-8 后上传。") from None
        if "\x00" in text:
            raise DocumentError("文件包含二进制内容，请上传纯文本 TXT 或 Markdown。")
        if not text:
            raise DocumentError("文件没有可读取的文字。")
        _check_text_limit(text)
        result = {"page_count": 1, "text": text, "pages": [{"number": 1, "text": text}], "warnings": []}
        source_type = "text"
    return {"filename": filename, "source_type": source_type, "sha256": hashlib.sha256(raw).hexdigest(), **result}


def _extract_pdf_subprocess(raw):
    # The parser does not need credentials. Preserve only OS/runtime configuration.
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "PYTHONPATH", "PYTHONHOME",
        "LANG", "LC_ALL", "TEAMBLOCKS_PDF_MEMORY_MB",
    }}
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "backend.documents", "--extract-pdf"],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT,
            env=environment, timeout=PDF_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise DocumentError("PDF 读取超过 20 秒，已停止解析。请拆分文件或另存为 TXT 后上传。", 422) from None
    except OSError:
        raise DocumentError("无法启动本地 PDF 读取程序，请检查 Python 运行环境。", 503) from None
    if completed.returncode != 0:
        raise DocumentError("PDF 解析未能完成，文件可能损坏或内容过于复杂。请重新导出或改用 TXT。", 422)
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise DocumentError("PDF 读取程序没有返回有效结果，请重新导出或改用 TXT。", 422) from None
    if "error" in result:
        raise DocumentError(result["error"], result.get("status", 400))
    return result


def _extract_pdf(raw):
    """Only invoked in the bounded worker; imports the optional PDF dependency lazily."""
    try:
        from pypdf import PdfReader, apply_configuration
        from pypdf.errors import LimitReachedError
    except ImportError:
        raise DocumentError("本地 PDF 依赖尚未安装，请先运行 python -m pip install -r requirements.txt。", 503) from None
    logging.getLogger("pypdf").disabled = True
    try:
        with apply_configuration(
            maximum_declared_stream_length=MAX_STREAM_BYTES,
            array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
            jbig2_maximum_output_length=MAX_STREAM_BYTES,
            lzw_maximum_output_length=MAX_STREAM_BYTES,
            run_length_maximum_output_length=MAX_STREAM_BYTES,
            zlib_maximum_output_length=MAX_STREAM_BYTES,
            brotli_maximum_output_length=MAX_STREAM_BYTES,
            image_maximum_buffer_size=MAX_STREAM_BYTES,
            stream_decoding_work_maximum_length=MAX_TOTAL_STREAM_BYTES,
            stream_parsing_work_maximum_count=250_000,
            page_tree_maximum_entries=2000,
            page_tree_maximum_depth=40,
            xform_maximum_invocations_per_extraction=500,
            jbig2dec_binary=None,
        ):
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if reader.is_encrypted:
                raise DocumentError("PDF 已加密，请先解除密码保护，再上传需求文档。")
            page_count = len(reader.pages)
            if not page_count:
                raise DocumentError("PDF 没有页面，请重新导出文件。")
            if page_count > MAX_PAGES:
                raise DocumentError("PDF 超过 40 页，请拆分后再上传，不会跳过后面的页面。", 413)
            pages, warnings, parts = [], [], []
            total_stream_bytes = 0
            for number, page in enumerate(reader.pages, 1):
                contents = page.get_contents()
                if contents is not None:
                    stream_length = len(contents.get_data())
                    total_stream_bytes += stream_length
                    if stream_length > MAX_STREAM_BYTES or total_stream_bytes > MAX_TOTAL_STREAM_BYTES:
                        raise DocumentError("PDF 解压后的内容过大，请简化文件或导出 TXT 后上传。", 413)
                text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n").strip()
                if not text:
                    warnings.append(f"第 {number} 页没有可提取文字，可能是扫描图片或空白页；这一页的内容没有被读取。")
                pages.append({"number": number, "text": text})
                parts.append(f"[Page {number}]\n{text}")
                _check_text_limit("\n\n".join(parts))
            if not any(page["text"] for page in pages):
                raise DocumentError("PDF 没有可提取的文字，可能是扫描件。当前不支持 OCR，请先转成文字版 PDF，或上传 TXT / Markdown。", 422)
            return {"page_count": page_count, "text": "\n\n".join(parts), "pages": pages, "warnings": warnings}
    except DocumentError:
        raise
    except (LimitReachedError, MemoryError):
        raise DocumentError("PDF 内容超出本地解析限制，请拆分文件或导出 TXT 后上传。", 413) from None
    except Exception:
        # PDF parser exceptions may contain document contents or private metadata.
        raise DocumentError("无法读取这个 PDF，文件可能损坏。请重新导出 PDF 或上传 TXT / Markdown。") from None


def _limit_worker_memory():
    """Best-effort OS cap in addition to mandatory decompression and wall-time limits."""
    try:
        memory_mb = max(128, min(int(os.environ.get("TEAMBLOCKS_PDF_MEMORY_MB", "768")), 2048))
    except ValueError:
        memory_mb = 768
    memory_bytes = memory_mb * 1024 * 1024
    if os.name != "nt":
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (PDF_TIMEOUT_SECONDS, PDF_TIMEOUT_SECONDS))
        except (ImportError, ValueError, OSError):
            pass
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            return None
        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        limits.ProcessMemoryLimit = memory_bytes
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            kernel.CloseHandle(handle)
            return None
        # Keep the job handle alive until the short-lived worker exits.
        return handle
    except (ImportError, AttributeError, OSError):
        return None


def _worker():
    memory_job = _limit_worker_memory()
    try:
        raw = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise DocumentError("文件超过 5 MiB。", 413)
        result = _extract_pdf(raw)
    except DocumentError as exc:
        result = {"error": str(exc), "status": exc.status}
    except Exception:
        result = {"error": "本地 PDF 读取程序无法完成解析，请重新导出或改用 TXT。", "status": 422}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    return memory_job


if __name__ == "__main__" and sys.argv[1:] == ["--extract-pdf"]:
    _worker()
