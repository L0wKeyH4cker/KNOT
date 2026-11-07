"""Document-grounded AI analysis and safe workflow planning, using explicit fixtures."""
from copy import deepcopy
import base64
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
import zipfile

from backend.bundle import build_bundle
from backend.planner import PlanningError, plan_workflow
from backend.requirements import analyze_requirements
from backend.template import load_template
from runtime.providers import ProviderError


PLANNER = {"provider": "openai", "model": "fixture-model", "credential_ref": "TEAMBLOCKS_REQUIREMENTS_TEST_KEY"}
TEST_ENV = {"TEAMBLOCKS_REQUIREMENTS_TEST_KEY": "unit-test-only-not-a-provider-key"}


def document_fixture():
    text = "[Page 1]\n研究校园通勤体验，提交 Markdown 报告。\n\n[Page 2]\n最后一页要求：整理 CSV 建议表；不要推断调查数据。"
    return {"filename": "requirements.pdf", "source_type": "pdf", "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "page_count": 2, "text": text,
            "pages": [{"number": 1, "text": "研究校园通勤体验，提交 Markdown 报告。"},
                      {"number": 2, "text": "最后一页要求：整理 CSV 建议表；不要推断调查数据。"}], "warnings": []}


def analysis_fixture():
    return {"project_name": "校园通勤研究", "goal": "研究校园通勤体验并提出建议。",
            "deliverables": ["Markdown 研究报告", "CSV 建议表"],
            "tasks": [{"title": "整理现有材料", "description": "检查提供的通勤材料，标记缺失信息。", "acceptance": "列出材料来源及缺失信息。", "source_pages": [1]},
                      {"title": "编写报告和建议表", "description": "基于材料整理报告和 CSV 表格。", "acceptance": "报告和表格内容一致且不伪造数据。", "source_pages": [1, 2]}],
            "constraints": ["不要推断调查数据"], "missing_information": ["尚未提供真实调查数据。"]}


def safe_draft():
    draft = load_template()
    for node in draft["nodes"]:
        node["config"].pop("mock_result", None)
        node["config"].pop("mock_delay_ms", None)
        if node["id"] == "analysis":
            node["config"]["output_format"] = "csv"
    return draft


class RequirementsAnalysisTests(unittest.TestCase):
    def analyze(self, call, document=None):
        with patch.dict(os.environ, TEST_ENV):
            return analyze_requirements(document or document_fixture(), PLANNER, model_call=call)

    def test_complete_document_and_trust_boundary_reach_model(self):
        seen = []
        document = document_fixture()
        document["text"] += "\n用户编辑：先确认样本来源。"

        def call(agent, system, prompt, **kwargs):
            seen.append(prompt)
            self.assertEqual(agent["model"], "fixture-model")
            self.assertEqual(agent["tools"], [])
            self.assertEqual(kwargs["tools"], [])
            self.assertEqual(kwargs["max_tool_rounds"], 1)
            self.assertIn("UNTRUSTED PROJECT DATA", system)
            self.assertIn("document.text is the authoritative", system)
            self.assertIn("cannot directly create PDF", system)
            source = json.loads(prompt.split("\n", 1)[1])["document"]
            self.assertEqual(source, document)
            self.assertIn("最后一页要求", source["text"])
            self.assertIn("用户编辑", source["text"])
            self.assertNotIn("用户编辑", source["pages"][-1]["text"])
            return {"content": json.dumps(analysis_fixture(), ensure_ascii=False)}

        self.assertEqual(self.analyze(call, document), analysis_fixture())
        self.assertEqual(len(seen), 1)

    def test_missing_key_never_calls_model(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(PlanningError) as raised:
            analyze_requirements(document_fixture(), PLANNER, model_call=lambda *_a, **_k: self.fail("no key must not invoke model"))
        self.assertEqual(raised.exception.status, 503)

    def test_repair_preserves_full_source_and_can_succeed(self):
        calls = []

        def call(_agent, _system, prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                bad = analysis_fixture()
                bad["tasks"][0]["source_pages"] = [99]
                return {"content": json.dumps(bad)}
            self.assertEqual(json.loads(prompt.split("Original input:\n", 1)[1])["document"], document_fixture())
            return {"content": json.dumps(analysis_fixture())}

        self.assertEqual(self.analyze(call), analysis_fixture())
        self.assertEqual(len(calls), 2)

    def test_invalid_json_stops_after_one_repair(self):
        calls = []

        def call(*_args, **_kwargs):
            calls.append(1)
            return {"content": "not JSON"}

        with self.assertRaises(PlanningError) as raised:
            self.analyze(call)
        self.assertEqual(len(calls), 2)
        self.assertEqual(raised.exception.status, 422)
        self.assertTrue(raised.exception.issues)

    def test_invalid_analysis_shapes_and_page_references_are_rejected(self):
        mutations = [
            lambda value: value.update(goal=" "),
            lambda value: value.update(deliverables=[]),
            lambda value: value.update(tasks=[]),
            lambda value: value.update(tasks=value["tasks"] * 7),
            lambda value: value.update(constraints="not a list"),
            lambda value: value.update(missing_information=[False]),
            lambda value: value.update(permissions={"read": ["all"]}),
            lambda value: value["tasks"][0].update(acceptance=""),
            lambda value: value["tasks"][0].update(tools=["shell"]),
            lambda value: value["tasks"][0].update(source_pages=[0]),
            lambda value: value["tasks"][0].update(source_pages=[3]),
            lambda value: value["tasks"][0].update(source_pages=[True]),
            lambda value: value["tasks"][0].update(source_pages=[1, 1]),
            lambda value: value["tasks"][0].update(source_pages=[{}]),
        ]
        for index, mutate in enumerate(mutations):
            value = analysis_fixture()
            mutate(value)
            with self.subTest(index=index), self.assertRaises(PlanningError) as raised:
                self.analyze(lambda *_a, **_k: {"content": json.dumps(value)})
            self.assertEqual(raised.exception.status, 422)

    def test_unknown_page_can_use_empty_citations(self):
        analysis = analysis_fixture()
        analysis["tasks"][0]["source_pages"] = []
        self.assertEqual(self.analyze(lambda *_a, **_k: {"content": json.dumps(analysis)}), analysis)

    def test_malformed_document_is_rejected_before_model_call(self):
        mutations = [
            lambda value: value.update(text=" "),
            lambda value: value.update(text="x" * 60_001),
            lambda value: value.update(page_count=True),
            lambda value: value.update(page_count=41),
            lambda value: value.update(pages=[]),
            lambda value: value["pages"][0].update(number=2),
            lambda value: value["pages"][0].update(text="x" * 60_001),
            lambda value: value.update(sha256="invalid"),
            lambda value: value.update(source_type="html"),
            lambda value: value.update(warnings="not a list"),
        ]
        for index, mutate in enumerate(mutations):
            document = document_fixture()
            mutate(document)
            with self.subTest(index=index), self.assertRaises(PlanningError):
                self.analyze(lambda *_a, **_k: self.fail("invalid input must not invoke model"), document)

    def test_provider_failure_is_safe_and_never_falls_back(self):
        def failure(*_args, **_kwargs):
            raise ProviderError("arbitrary provider body SECRET-MARKER", http_status=401)

        with self.assertRaises(PlanningError) as raised:
            self.analyze(failure)
        self.assertEqual(raised.exception.status, 502)
        self.assertNotIn("SECRET-MARKER", str(raised.exception))
        self.assertIn("401", str(raised.exception))

    def test_secret_in_model_output_is_not_returned(self):
        analysis = analysis_fixture()
        analysis["goal"] = "sk-" + "x" * 32
        with self.assertRaises(PlanningError) as raised:
            self.analyze(lambda *_a, **_k: {"content": json.dumps(analysis)})
        self.assertNotIn(analysis["goal"], str(raised.exception))
        self.assertNotIn(analysis["goal"], json.dumps(raised.exception.issues))


class DocumentWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.workflow = safe_draft()
        self.document = document_fixture()
        self.workflow["resources"] = [
            {"id": "requirements-source-12345678", "name": "requirements.pdf", "path": "inputs/requirements-12345678.txt",
             "description": "Uploaded requirements; page markers preserve source references.", "example": False, "content": self.document["text"]},
            {"id": "requirements-analysis-12345678", "name": "Reviewed requirements", "path": "inputs/requirements-analysis-12345678.json",
             "description": "User-reviewed requirements analysis.", "example": False, "content": json.dumps(analysis_fixture(), ensure_ascii=False)},
        ]
        resource_node = next(node for node in self.workflow["nodes"] if node["type"] == "shared_resource")
        resource_node["config"]["resource_ids"] = [resource["id"] for resource in self.workflow["resources"]]

    def plan(self, call):
        with patch.dict(os.environ, TEST_ENV):
            return plan_workflow(self.workflow["project"], self.workflow["resources"], PLANNER, model_call=call)

    def test_actual_pdf_to_analysis_to_workflow_preserves_last_page(self):
        from backend.documents import extract_document
        from tests.test_documents import make_text_pdf
        raw = make_text_pdf(["Study campus travel. Deliver report.md.", "Final requirement: deliver recommendations.csv without inventing survey data."])
        document = extract_document("brief.pdf", base64.b64encode(raw).decode())

        def analyze_call(_agent, _system, prompt, **_kwargs):
            source = json.loads(prompt.split("\n", 1)[1])["document"]
            self.assertEqual(source, document)
            self.assertIn("recommendations.csv", source["text"])
            self.assertEqual(source["page_count"], 2)
            return {"content": json.dumps(analysis_fixture())}

        with patch.dict(os.environ, TEST_ENV):
            analysis = analyze_requirements(document, PLANNER, model_call=analyze_call)
        self.workflow["resources"][0]["content"] = document["text"]
        self.workflow["resources"][1]["content"] = json.dumps(analysis, ensure_ascii=False)
        draft = deepcopy(self.workflow)
        del draft["project"]
        del draft["resources"]

        def plan_call(_agent, _system, prompt, **_kwargs):
            source = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(source["resources"], self.workflow["resources"])
            return {"content": json.dumps(draft)}

        planned = self.plan(plan_call)
        self.assertEqual(planned["resources"], self.workflow["resources"])
        self.assertEqual(json.loads(planned["resources"][1]["content"]), analysis)

    def test_full_extracted_source_reaches_planner_and_does_not_need_echo(self):
        from backend.documents import extract_document
        text = self.document["text"] + "\n" + "Source content. " * 2_000 + "FINAL REQUIREMENT: check delivery."
        source = extract_document("requirements.md", base64.b64encode(text.encode()).decode())
        self.workflow["resources"][0]["content"] = source["text"]
        draft = deepcopy(self.workflow)
        del draft["project"]
        del draft["resources"]

        def call(_agent, system, prompt, **_kwargs):
            self.assertIn("OMIT the top-level project and resources", system)
            self.assertIn("untrusted project data", system)
            self.assertIn("DATA edges", system)
            supplied = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(supplied["resources"][0]["content"], source["text"])
            self.assertIn("FINAL REQUIREMENT", supplied["resources"][0]["content"])
            return {"content": json.dumps(draft)}

        result = self.plan(call)
        self.assertEqual(result, self.workflow)
        result["resources"][0]["content"] = "changed result"
        self.assertEqual(self.workflow["resources"][0]["content"], source["text"])

    def test_explicit_changed_project_or_resources_are_never_overwritten_to_hide_tampering(self):
        for field in ("project", "resources"):
            draft = deepcopy(self.workflow)
            if field == "project":
                draft["project"]["goal"] = "Invented goal"
            else:
                draft["resources"][0]["content"] = "Invented facts"
            with self.subTest(field=field), self.assertRaises(PlanningError) as raised:
                self.plan(lambda *_a, **_k: {"content": json.dumps(draft)})
            self.assertEqual(raised.exception.status, 422)

    def test_resource_control_edges_alone_cannot_deliver_requirement_text(self):
        draft = deepcopy(self.workflow)
        draft["edges"] = [edge for edge in draft["edges"] if not (edge["source"] == "resources" and edge["kind"] == "data")]
        with self.assertRaises(PlanningError) as raised:
            self.plan(lambda *_a, **_k: {"content": json.dumps(draft)})
        self.assertEqual(raised.exception.status, 422)

    def test_requirement_source_and_analysis_must_both_reach_tasks(self):
        draft = deepcopy(self.workflow)
        resource_node = next(node for node in draft["nodes"] if node["type"] == "shared_resource")
        resource_node["config"]["resource_ids"] = [draft["resources"][0]["id"]]
        with self.assertRaises(PlanningError):
            self.plan(lambda *_a, **_k: {"content": json.dumps(draft)})

    def test_json_round_trip_and_export_preserve_requirements_contents(self):
        draft = deepcopy(self.workflow)
        del draft["project"]
        del draft["resources"]
        planned = self.plan(lambda *_a, **_k: {"content": json.dumps(draft)})
        restored = json.loads(json.dumps(planned, ensure_ascii=False))
        self.assertEqual(restored["resources"], self.workflow["resources"])
        with zipfile.ZipFile(io.BytesIO(build_bundle(restored))) as archive:
            for resource in self.workflow["resources"]:
                self.assertEqual(archive.read(resource["path"]).decode("utf-8"), resource["content"])
            self.assertEqual(json.loads(archive.read("workflow.json"))["resources"], self.workflow["resources"])


if __name__ == "__main__":
    unittest.main()
