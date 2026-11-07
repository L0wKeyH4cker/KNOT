"""Backend contracts, conservative AI drafts, and independent exported execution."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

from backend.bundle import BundleError, build_bundle, reject_secrets, resource_archive_path
from backend.planner import PlanningError, plan_workflow
from backend.template import load_template
from runtime.validation import validate_workflow
from server import Handler, ThreadingHTTPServer
from runtime.engine import Engine


def temporary_run(prefix):
    temporary_root = Path(__file__).resolve().parents[1] / ".test-tmp"
    temporary_root.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=temporary_root)


def valid_ai_draft():
    draft = load_template()
    for node in draft["nodes"]:
        node["config"].pop("mock_result", None)
        node["config"].pop("mock_delay_ms", None)
        if node["id"] == "analysis":
            node["config"]["output_format"] = "csv"
    return draft


class BundleTests(unittest.TestCase):
    def test_demo_validates_for_mock_and_warns_about_real_models(self):
        issues = validate_workflow(load_template())
        self.assertFalse([i for i in issues if i["severity"] == "error"], issues)
        self.assertTrue([i for i in issues if i["code"] == "model"])
        self.assertTrue([i for i in validate_workflow(load_template(), mode="real") if i["severity"] == "error"])

    def test_bundle_preserves_exact_configuration_and_contains_no_machine_paths(self):
        workflow = load_template()
        workflow["nodes"][3]["position"]["x"] = 177
        workflow["nodes"][3]["config"]["permissions"]["read"] = ["inputs/example-interviews.md"]
        archive = zipfile.ZipFile(io.BytesIO(build_bundle(workflow)))
        self.assertEqual(json.loads(archive.read("workflow.json")), workflow)
        for expected in ("run.py", "runtime/engine.py", "requirements.txt", ".env.example", "start.bat", "start.sh", "README.md", "inputs/example-survey.csv"):
            self.assertIn(expected, archive.namelist())
        for info in archive.infolist():
            self.assertNotIn("..", Path(info.filename).parts)
            self.assertNotIn(str(Path.cwd()).encode(), archive.read(info.filename))
        self.assertIn(b"OPENAI_API_KEY=", archive.read(".env.example"))

    def test_bundle_rejects_cycles_and_secret_literals(self):
        workflow = load_template()
        workflow["edges"].append({"id": "back-edge", "source": "synthesis", "target": "parallel", "kind": "control", "source_port": "out", "target_port": "in"})
        with self.assertRaises(BundleError):
            build_bundle(workflow)
        with self.assertRaises(BundleError):
            reject_secrets({"fake_fixture": "sk-" + "x" * 32})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-secret-credential"}):
            with self.assertRaises(BundleError):
                reject_secrets({"goal": "unit-test-secret-credential"})

    def test_resource_paths_cannot_escape_archive(self):
        for path in ("../outside", "inputs/../outside", "C:/inputs/a", "inputs\\a.txt", "/inputs/a.txt", "inputs/CON.txt"):
            with self.subTest(path=path), self.assertRaises(BundleError):
                resource_archive_path(path)

    def test_input_readme_is_never_overwritten_by_bundle_metadata(self):
        workflow = load_template()
        workflow["resources"][0]["path"] = "inputs/README.txt"
        archive = zipfile.ZipFile(io.BytesIO(build_bundle(workflow)))
        self.assertEqual(archive.namelist().count("inputs/README.txt"), 1)
        self.assertEqual(archive.read("inputs/README.txt").decode(), workflow["resources"][0]["content"])

    def test_export_runs_in_fresh_directory_and_waits_before_delivery(self):
        workflow = load_template()
        with temporary_run("teamblocks-independent-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(workflow))) as archive:
                archive.extractall(root)
            first = subprocess.run([sys.executable, "run.py", "--mode", "mock"], cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
            state = json.loads((root / "logs/run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "waiting_review")
            self.assertFalse((root / "results/report.md").exists())
            self.assertFalse((root / "results/summary.csv").exists())
            second = subprocess.run([sys.executable, "run.py", "--mode", "mock", "--resume", "--review", "review", "--decision", "approve", "--reviewer", "member-3"], cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("MOCK", (root / "results/report.md").read_text(encoding="utf-8"))
            self.assertIn("Walk", (root / "results/summary.csv").read_text(encoding="utf-8-sig"))

    def test_node_edit_changes_exported_execution(self):
        workflow = load_template()
        workflow["nodes"][5]["config"]["mock_result"]["content"] = "# Modified by the canvas\n"
        workflow["nodes"][7]["config"]["mappings"][0]["filename"] = "edited-report.md"
        with temporary_run("teamblocks-edit-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(workflow))) as archive:
                archive.extractall(root)
            subprocess.run([sys.executable, "run.py", "--mode", "mock"], cwd=root, capture_output=True, timeout=20)
            completed = subprocess.run([sys.executable, "run.py", "--mode", "mock", "--resume", "--review", "review", "--decision", "approve", "--reviewer", "member-3"], cwd=root, capture_output=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual((root / "results/edited-report.md").read_text(encoding="utf-8").strip(), "# Modified by the canvas")
            self.assertFalse((root / "results/report.md").exists())


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.workflow = valid_ai_draft()
        self.planner = {"provider": "openai", "model": "fixture-model", "credential_ref": "TEAMBLOCKS_TEST_PLANNER_KEY"}

    def plan(self, call):
        with patch.dict(os.environ, {"TEAMBLOCKS_TEST_PLANNER_KEY": "unit-test-only-not-a-provider-key"}):
            return plan_workflow(self.workflow["project"], self.workflow["resources"], self.planner, model_call=call)

    def test_absent_key_is_explicit_and_never_calls_model(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PlanningError) as context:
                plan_workflow(self.workflow["project"], [], self.planner, model_call=lambda *_args, **_kwargs: self.fail("must not call"))
            self.assertEqual(context.exception.status, 503)

    def test_valid_structured_draft_is_returned_editable(self):
        result = self.plan(lambda *_args, **_kwargs: {"content": json.dumps(self.workflow)})
        self.assertEqual(result, self.workflow)
        result["nodes"][0]["position"]["x"] = 999
        self.assertEqual(result["nodes"][0]["position"]["x"], 999)

    def test_project_only_input_generates_complete_mock_runnable_roles(self):
        draft = deepcopy(self.workflow)
        draft["resources"] = []
        draft["nodes"] = [node for node in draft["nodes"] if node["id"] != "resources"]
        draft["edges"] = [edge for edge in draft["edges"] if "resources" not in (edge["source"], edge["target"])]
        draft["edges"].append({"id": "start-parallel", "source": "start", "target": "parallel", "kind": "control", "source_port": "out", "target_port": "in"})
        with patch.dict(os.environ, {"TEAMBLOCKS_TEST_PLANNER_KEY": "unit-test-only-not-a-provider-key"}):
            result = plan_workflow(draft["project"], [], self.planner, model_call=lambda *_a, **_k: {"content": json.dumps(draft)})
        self.assertTrue(all(agent["model"] == "" and agent["role"] and agent["system_prompt"] for agent in result["agents"]))
        self.assertEqual(set(result), {"schema_version", "project", "agents", "nodes", "edges", "resources", "limits", "viewport", "design_notes"})
        with temporary_run("ai-draft-mock-") as directory:
            engine = Engine(result, directory, mode="mock")
            self.assertEqual(engine.run()["status"], "waiting_review")
            engine.resume("review", "approve", "member-3")
            self.assertEqual(engine.run()["status"], "completed")
            self.assertTrue((Path(directory) / "results/summary.csv").is_file())

    def test_ai_must_supply_explicit_blank_execution_model_and_mock_safe_csv(self):
        for mutation in ("missing_model", "missing_tools", "csv_source", "no_reasoning"):
            invalid = deepcopy(self.workflow)
            if mutation == "missing_model":
                invalid["agents"][0].pop("model")
            elif mutation == "missing_tools":
                invalid["nodes"][3]["config"].pop("tools")
            elif mutation == "csv_source":
                invalid["nodes"][4]["config"]["output_format"] = "json"
            else:
                invalid["design_notes"] = []
            with self.subTest(mutation=mutation), self.assertRaises(PlanningError):
                self.plan(lambda *_args, **_kwargs: {"content": json.dumps(invalid)})

    def test_invalid_drafts_get_at_most_two_repairs(self):
        calls = []

        def bad(*args, **kwargs):
            calls.append(1)
            return {"content": "not JSON"}

        with self.assertRaises(PlanningError) as context:
            self.plan(bad)
        self.assertEqual(len(calls), 3)
        self.assertEqual(context.exception.status, 422)

    def test_repair_can_fix_invalid_json(self):
        calls = []

        def repaired(*args, **kwargs):
            calls.append(1)
            return {"content": "bad" if len(calls) == 1 else json.dumps(self.workflow)}

        self.assertEqual(self.plan(repaired), self.workflow)
        self.assertEqual(len(calls), 2)

    def test_planner_cannot_expand_permissions_or_invent_resources(self):
        invalid = deepcopy(self.workflow)
        invalid["nodes"][3]["config"]["permissions"]["read"] = ["inputs/"]
        with self.assertRaises(PlanningError):
            self.plan(lambda *_args, **_kwargs: {"content": json.dumps(invalid)})
        invalid = deepcopy(self.workflow)
        invalid["project"]["members"][0]["skills"] = "Invented professional expertise"
        with self.assertRaises(PlanningError):
            self.plan(lambda *_args, **_kwargs: {"content": json.dumps(invalid)})

    def test_provider_failure_does_not_fall_back_to_mock(self):
        def failure(*args, **kwargs):
            raise RuntimeError("provider unavailable")
        with self.assertRaises(PlanningError) as context:
            self.plan(failure)
        self.assertEqual(context.exception.status, 502)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, path, value, headers=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(value).encode(), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        return urllib.request.urlopen(request, timeout=10)

    def test_health_template_validate_export(self):
        with urllib.request.urlopen(self.base + "/api/health") as response:
            health = json.load(response)
        self.assertTrue(health["ok"])
        self.assertTrue(all(isinstance(v, bool) for v in health["planner_credentials"].values()))
        with urllib.request.urlopen(self.base + "/api/template") as response:
            workflow = json.load(response)
        with self.post("/api/validate", {"workflow": workflow}) as response:
            self.assertFalse([i for i in json.load(response)["issues"] if i["severity"] == "error"])
        with self.post("/api/export", {"workflow": workflow}) as response:
            self.assertEqual(response.headers.get_content_type(), "application/zip")
            self.assertIn("workflow.json", zipfile.ZipFile(io.BytesIO(response.read())).namelist())

    def test_cross_origin_write_and_filesystem_escape_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.post("/api/export", {"workflow": load_template()}, {"Origin": "https://example.org"})
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.base + "/%2e%2e/.env")
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_credential_endpoint_activates_local_key_and_tests_without_exposing_it(self):
        fixture = "dummy-local-route-credential"
        with temporary_run("teamblocks-credential-route-") as directory, patch("server.ROOT", Path(directory)), patch.dict(os.environ, {}, clear=True):
            with self.post("/api/credentials", {"credential_ref": "DEEPSEEK_API_KEY", "key": fixture}) as response:
                payload = json.load(response)
            self.assertTrue(payload["credentials"]["DEEPSEEK_API_KEY"])
            self.assertNotIn(fixture, json.dumps(payload))
            with urllib.request.urlopen(self.base + "/api/health") as response:
                health = json.load(response)
            connection = health["default_planner"]
            self.assertEqual(connection["credential_ref"], "DEEPSEEK_API_KEY")
            self.assertNotIn(fixture, json.dumps(health))
            with patch("backend.connections._post", return_value={"choices": [{"message": {"content": "OK"}}]}):
                with self.post("/api/connection/test", {"connection": connection}) as response:
                    checked = json.load(response)
            self.assertTrue(checked["ok"])
            self.assertNotIn(fixture, json.dumps(checked))

    def test_credential_endpoint_rejects_cross_origin_before_writing(self):
        with temporary_run("teamblocks-credential-origin-") as directory, patch("server.ROOT", Path(directory)):
            with self.assertRaises(urllib.error.HTTPError) as result:
                self.post("/api/credentials", {"credential_ref": "DEEPSEEK_API_KEY", "key": "dummy-blocked-origin-key"}, {"Origin": "https://example.org"})
            self.assertEqual(result.exception.code, 403)
            result.exception.close()
            self.assertFalse((Path(directory) / ".env.local").exists())

    def test_secret_input_is_rejected_without_echoing_it(self):
        fixture_secret = "unit-test-never-a-real-provider-credential"
        workflow = load_template()
        workflow["nodes"][3]["config"]["api_key"] = fixture_secret
        with patch.dict(os.environ, {"OPENAI_API_KEY": fixture_secret}):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.post("/api/export", {"workflow": workflow})
            response = context.exception.read().decode()
            context.exception.close()
        self.assertNotIn(fixture_secret, response)
        self.assertEqual(context.exception.code, 400)

    def test_planner_error_payload_redacts_all_issue_fields(self):
        fixture_secret = "unit-test-redact-custom-planner-secret"
        with patch.dict(os.environ, {"TEAMBLOCKS_TEST_PLANNER_KEY": fixture_secret}), patch("server.plan_workflow", side_effect=PlanningError(fixture_secret, status=422, issues=[{"message": fixture_secret}])):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.post("/api/plan", {})
            response = context.exception.read().decode()
            context.exception.close()
        self.assertNotIn(fixture_secret, response)
        self.assertIn("REDACTED", response)


if __name__ == "__main__":
    unittest.main()
