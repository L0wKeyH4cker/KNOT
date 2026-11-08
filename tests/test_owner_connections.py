"""Owner-specific local coding routes with fixture workers; no real model requests."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import run
from runtime.engine import Engine, WorkflowError
from runtime.local_config import DEFAULT_EXECUTION, validate_execution
from runtime.owner_connections import resolve_owner_connection, validate_owner_connections
from runtime.validation import validate_workflow
from tests.test_runtime import workflow


EXECUTION = {**DEFAULT_EXECUTION, "backend": "opencode", "task_timeout_seconds": 60}
REF_A = "KNOT_OWNER_ALICE_CREDENTIAL"
REF_B = "KNOT_OWNER_BOB_CREDENTIAL"


def owner_workflow(review=False):
    flow = workflow(review)
    flow["project"]["members"][0]["connection"] = {
        "provider": "openai", "model": "fixture-alice", "credential_ref": REF_A,
    }
    flow["project"]["members"].append({"id": "bob", "name": "Bob", "skills": "", "connection": {
        "provider": "openai", "model": "fixture-bob", "credential_ref": REF_B,
        "base_url": "https://example.invalid/v1",
    }})
    next(n for n in flow["nodes"] if n["id"] == "right")["config"]["owner_id"] = "bob"
    return flow


class OwnerConnectionTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="owner-routing-", dir=scratch)
        self.root = Path(temporary.name)
        self.addCleanup(temporary.cleanup)
        self.credentials = {REF_A: "fixture-private-alice-2034", REF_B: "fixture-private-bob-7291"}
        env = patch.dict(os.environ, self.credentials)
        env.start()
        self.addCleanup(env.stop)
        self.calls = []

    def engine(self, flow):
        engine = Engine(flow, self.root, "local", execution=EXECUTION)
        engine.quiet = True
        return engine

    def worker(self, backend, model, cwd, prompt, timeout, *, event_callback=None, connection=None):
        task = json.loads(prompt.split("Assigned work:\n", 1)[1])["task"]["id"]
        self.assertEqual(backend, "opencode")
        expected = ("bob", REF_B, "fixture-bob") if task == "right" else ("member", REF_A, "fixture-alice")
        self.assertEqual((connection["owner_id"], connection["credential_ref"], model), expected)
        self.assertEqual(model, connection["model"])
        for value in self.credentials.values():
            self.assertNotIn(value, prompt + json.dumps(connection))
        self.calls.append(task)
        if task == "join":
            self.assertTrue((cwd / "left.py").is_file())
            self.assertTrue((cwd / "right.py").is_file())
        (cwd / (task + ".py")).write_text("value = 1\n", encoding="utf-8")
        return {"content": "Completed " + task, "data": {"task": task}, "checks": []}

    def test_draft_connection_can_be_incomplete_but_opencode_requires_it(self):
        flow = owner_workflow()
        flow["project"]["members"][0]["connection"] = {"provider": "openai", "model": "", "credential_ref": ""}
        self.assertEqual(validate_workflow(flow, "local"), [])
        issues = validate_owner_connections(flow)
        self.assertEqual({i["node_id"] for i in issues}, {"left", "join"})
        with patch("runtime.coding.run_coding_task") as worker:
            with self.assertRaises(WorkflowError):
                self.engine(flow)
        worker.assert_not_called()
        self.assertFalse((self.root / "logs").exists())

    def test_structural_validation_rejects_secret_and_unsafe_connection_fields(self):
        for patch_value in ({"api_key": "secret"}, {"model": "../../other"}, {"provider": "unknown"},
                            {"credential_ref": "not a name"}, {"base_url": "https://fixture-user@example.invalid"},
                            {"base_url": "https://example.invalid:bad"}, {"model": ["wrong type"]}):
            with self.subTest(value=patch_value):
                flow = owner_workflow()
                flow["project"]["members"][0]["connection"].update(patch_value)
                self.assertIn("member_connection", {i["code"] for i in validate_workflow(flow, "local")})

    def test_review_only_member_does_not_need_a_connection(self):
        flow = owner_workflow(True)
        flow["project"]["members"].append({"id": "reviewer", "name": "Reviewer", "skills": ""})
        next(n for n in flow["nodes"] if n["id"] == "review")["config"]["owner_id"] = "reviewer"
        self.assertEqual(validate_owner_connections(flow, require_credentials=True), [])

    def test_missing_owner_key_never_uses_another_key(self):
        flow = owner_workflow()
        with patch.dict(os.environ, {REF_B: "   ", "OPENAI_API_KEY": "fixture-unrelated-global-key"}):
            self.assertEqual(validate_owner_connections(flow), [])
            issues = validate_owner_connections(flow, require_credentials=True)
            self.assertEqual([(i["code"], i["node_id"]) for i in issues], [("owner_credential_missing", "right")])
            with patch("runtime.coding.run_coding_task") as worker:
                with self.assertRaises(WorkflowError):
                    self.engine(flow)
            worker.assert_not_called()
        self.assertFalse((self.root / "logs").exists())

    def test_resolver_uses_owner_and_ignores_legacy_agent_connection(self):
        flow = owner_workflow()
        right = next(n for n in flow["nodes"] if n["id"] == "right")
        route = resolve_owner_connection(flow, right)
        self.assertEqual(route["credential_ref"], REF_B)
        self.assertEqual(route["owner_name"], "Bob")
        self.assertNotEqual(route["credential_ref"], flow["agents"][0]["credential_ref"])

    def test_distinct_task_owners_cannot_share_a_credential_reference(self):
        flow = owner_workflow()
        flow["project"]["members"][1]["connection"]["credential_ref"] = REF_A
        issues = validate_owner_connections(flow)
        self.assertEqual([(i["code"], i["node_id"]) for i in issues], [("owner_credential_duplicate", "right")])
        with self.assertRaises(WorkflowError):
            self.engine(flow)

    def test_one_owner_can_reuse_their_connection_for_several_tasks(self):
        flow = owner_workflow()
        for node in flow["nodes"]:
            if node["type"] == "agent_task":
                node["config"]["owner_id"] = "member"
        # An unused member's matching reference is not a collision in this run.
        flow["project"]["members"][1]["connection"]["credential_ref"] = REF_A
        self.assertEqual(validate_owner_connections(flow, require_credentials=True), [])

    def test_parallel_owners_keep_separate_models_and_source_handoffs(self):
        barrier = threading.Barrier(2)
        def worker(*args, **kwargs):
            result = self.worker(*args, **kwargs)
            if result["data"]["task"] in ("left", "right"):
                barrier.wait(timeout=5)
            return result
        with patch("runtime.coding.run_coding_task", side_effect=worker):
            state = self.engine(owner_workflow()).run()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(set(self.calls), {"left", "right", "join"})
        self.assertEqual(state["task_routes"]["right"]["credential_ref"], REF_B)
        self.assertEqual(state["nodes"]["right"]["owner_name"], "Bob")
        self.assertEqual(state["results"]["right"]["model"], "fixture-bob")
        self.assertTrue((self.root / "results/project/join.py").exists())
        progress = json.loads((self.root / "logs/run-state.progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["nodes"]["right"]["model"], "fixture-bob")
        self.assertEqual(progress["nodes"]["right"]["owner_name"], "Bob")
        for path in (self.root / "logs").iterdir():
            for value in self.credentials.values():
                self.assertNotIn(value, path.read_text(encoding="utf-8"))

    def test_key_rotation_preserves_review_resume_and_does_not_rerun_tasks(self):
        flow = owner_workflow(True)
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            self.assertEqual(self.engine(flow).run()["status"], "waiting_review")
            with patch.dict(os.environ, {REF_A: "fixture-rotated-alice-4831"}):
                state = self.engine(flow).resume("review", "approve", "member").run()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(self.calls), 3)

    def test_changed_owner_model_cannot_resume_previous_review(self):
        flow = owner_workflow(True)
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            self.engine(flow).run()
        changed = copy.deepcopy(flow)
        changed["project"]["members"][0]["connection"]["model"] = "different-model"
        with self.assertRaisesRegex(ValueError, "Workflow changed"):
            self.engine(changed).resume("review", "approve", "member")

    def test_modified_route_snapshot_cannot_resume(self):
        flow = owner_workflow(True)
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            state = self.engine(flow).run()
        state["task_routes"]["right"]["credential_ref"] = REF_A
        (self.root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Task owner connections changed"):
            self.engine(flow).resume("review", "approve", "member")

    def test_owner_failure_redacts_key_and_retry_keeps_successful_work(self):
        flow = owner_workflow()
        def fail_left(*args, **kwargs):
            result = self.worker(*args, **kwargs)
            if result["data"]["task"] == "left":
                raise RuntimeError("Provider failed: " + self.credentials[REF_A])
            return result
        with patch("runtime.coding.run_coding_task", side_effect=fail_left):
            failed = self.engine(flow).run()
        self.assertEqual(failed["status"], "failed")
        self.assertIn("[REDACTED]", failed["nodes"]["left"]["error"])
        self.assertNotIn(self.credentials[REF_A], json.dumps(failed))
        with patch.dict(os.environ, {REF_A: "fixture-repaired-alice-9876"}), patch("runtime.coding.run_coding_task", side_effect=self.worker):
            state = self.engine(flow).retry_failed().run()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.calls.count("right"), 1)
        self.assertEqual(self.calls.count("left"), 2)

    def test_modified_route_snapshot_cannot_retry(self):
        flow = owner_workflow()
        with patch("runtime.coding.run_coding_task", side_effect=RuntimeError("fixture failure")):
            state = self.engine(flow).run()
        state["task_routes"]["left"]["model"] = "another-model"
        (self.root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Task owner connections changed"):
            self.engine(flow).retry_failed()

    def test_opencode_rejects_shared_model_but_legacy_configuration_is_unchanged(self):
        self.assertEqual(validate_execution(EXECUTION), EXECUTION)
        with self.assertRaisesRegex(ValueError, "shared model must be empty"):
            validate_execution({**EXECUTION, "model": "shared"})
        original = {**DEFAULT_EXECUTION, "backend": "codex", "model": "shared"}
        self.assertEqual(validate_execution(original), original)

    def test_launcher_validate_checks_owner_keys_without_running_or_writing(self):
        (self.root / "workflow.json").write_text(json.dumps(owner_workflow()), encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {REF_B: ""}), patch("run.check_backend", return_value={"available": True}), \
                patch("run.Engine") as engine, contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = run.main(["--root", str(self.root), "--backend", "opencode", "--validate"])
        self.assertEqual(code, 1, errors.getvalue())
        payload = json.loads(output.getvalue())
        self.assertIn("owner_credential_missing", {i["code"] for i in payload["issues"]})
        engine.assert_not_called()
        self.assertFalse((self.root / "knot.json").exists())
        self.assertFalse((self.root / "logs").exists())

    def test_switch_to_opencode_removes_the_previous_shared_model(self):
        (self.root / "knot.json").write_text(json.dumps({**DEFAULT_EXECUTION, "backend": "codex", "model": "old-shared-model"}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), patch("run.Engine") as engine:
            code = run.main(["--root", str(self.root), "--backend", "opencode", "--configure"])
        self.assertEqual(code, 0)
        saved = json.loads((self.root / "knot.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["backend"], saved["model"]), ("opencode", ""))
        engine.assert_not_called()

    def test_editor_validation_checks_connections_without_requiring_host_keys(self):
        from server import Handler
        flow = owner_workflow()
        def validate(candidate):
            payload = json.dumps({"workflow": candidate, "mode": "local", "execution": EXECUTION}).encode()
            handler = object.__new__(Handler)
            handler.path = "/api/validate"
            handler.headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
            handler.rfile = io.BytesIO(payload)
            handler.send_json = Mock()
            handler.do_POST()
            status, result = handler.send_json.call_args.args
            self.assertEqual(status, 200, result)
            return result["issues"]
        with patch.dict(os.environ, {REF_A: "", REF_B: ""}):
            self.assertEqual(validate(flow), [])
            flow["project"]["members"][1]["connection"]["model"] = ""
            self.assertEqual([(i["code"], i["node_id"]) for i in validate(flow)], [("owner_connection", "right")])


if __name__ == "__main__":
    unittest.main()
