"""Explicit local retry preserves drafts and revalidates work; no model requests."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run
from runtime.engine import Engine
from runtime.local_config import save_execution
from runtime.workspace import LocalWorkspace
from tests.test_local_execution import EXECUTION
from tests.test_runtime import workflow


class LocalRetryTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="local-retry-", dir=scratch)
        self.root = Path(self.temp.name)
        self.flow = workflow(True)
        self.calls = []
        env = patch.dict(os.environ, {"KNOT_RUNS_DIR": str(self.root / ".test-registry")})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.temp.cleanup)

    def engine(self, flow=None, execution=None):
        engine = Engine(flow or self.flow, self.root, "local", execution=execution or EXECUTION)
        engine.quiet = True
        return engine

    def assignment(self, prompt):
        return json.loads(prompt.split("Assigned work:\n", 1)[1])["task"]["id"]

    def initial_worker(self, backend, model, cwd, prompt, timeout, **kwargs):
        task = self.assignment(prompt)
        self.calls.append((task, cwd))
        (cwd / (task + ".txt")).write_text("original " + task, encoding="utf-8")
        if task == "left":
            raise RuntimeError("Coding agent is blocked: preferred network method failed")
        return {"content": "Completed " + task, "data": {"files": [task + ".txt"]}, "checks": []}

    def fail_run(self):
        with patch("runtime.coding.run_coding_task", side_effect=self.initial_worker):
            state = self.engine().run()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["nodes"]["right"]["status"], "succeeded")
        return state

    def read_state(self):
        return json.loads((self.root / "logs/run-state.json").read_text(encoding="utf-8"))

    def save_state(self, state):
        (self.root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")

    def completed_worker(self, backend, model, cwd, prompt, timeout, **kwargs):
        task = self.assignment(prompt)
        self.calls.append((task, cwd))
        if task == "left":
            self.assertIn("explicitly requested retry", prompt)
            self.assertIn("preferred network method failed", prompt)
            self.assertIn("not proof of success", prompt)
            self.assertEqual((cwd / "left.txt").read_text(), "original left")
            (cwd / "verified.txt").write_text("actually checked", encoding="utf-8")
        if task == "join":
            self.assertEqual((cwd / "left.txt").read_text(), "original left")
            self.assertEqual((cwd / "right.txt").read_text(), "original right")
            self.assertTrue((cwd / "verified.txt").exists())
            (cwd / "joined.txt").write_text("both inputs verified", encoding="utf-8")
        return {"content": "Completed " + task, "data": {}, "checks": ["fixture validation"]}

    def test_retry_preserves_successes_old_drafts_and_human_review(self):
        failed = self.fail_run()
        original_bytes = (self.root / "logs/run-state.json").read_bytes()
        old_work = self.root / failed["nodes"]["left"]["workspace"]
        retry = self.engine().retry_failed()
        self.assertEqual(retry.state["nodes"]["right"], failed["nodes"]["right"])
        self.assertEqual(retry.state["results"]["right"], failed["results"]["right"])
        self.assertNotIn("left", retry.state["results"])
        self.assertEqual(retry.state["nodes"]["left"]["status"], "pending")
        backups = list((self.root / "logs").glob("run-state.before-retry-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original_bytes)
        with patch("runtime.coding.run_coding_task", side_effect=self.completed_worker):
            state = retry.run()
        self.assertEqual(state["status"], "waiting_review")
        self.assertEqual([task for task, _ in self.calls].count("right"), 1)
        self.assertEqual([task for task, _ in self.calls].count("left"), 2)
        self.assertEqual(state["nodes"]["left"]["attempts"], 2)
        history = state["nodes"]["left"]["attempt_history"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("preferred network method failed", history[0]["error"])
        self.assertNotEqual(self.root / state["nodes"]["left"]["workspace"], old_work)
        self.assertEqual((old_work / "left.txt").read_text(), "original left")
        self.assertNotIn("retry_from", state["nodes"]["left"])
        self.assertFalse((self.root / "results/project").exists())
        self.assertEqual(state["nodes"]["review"]["status"], "waiting_review")
        with patch("runtime.coding.run_coding_task") as worker:
            final = self.engine().resume("review", "approve", "member").run()
        worker.assert_not_called()
        self.assertEqual(final["status"], "completed")
        self.assertEqual((self.root / "results/project/left.txt").read_text(), "original left")

    def test_repeated_failure_uses_latest_draft_and_keeps_attempt_history(self):
        first = self.fail_run()
        first_work = self.root / first["nodes"]["left"]["workspace"]

        def fail_again(backend, model, cwd, prompt, timeout, **kwargs):
            self.assertEqual(self.assignment(prompt), "left")
            (cwd / "left.txt").write_text("second draft", encoding="utf-8")
            raise RuntimeError("Second attempt still lacks a required value")

        with patch("runtime.coding.run_coding_task", side_effect=fail_again):
            second = self.engine().retry_failed().run()
        second_work = self.root / second["nodes"]["left"]["workspace"]
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["nodes"]["left"]["attempts"], 2)
        self.assertEqual((first_work / "left.txt").read_text(), "original left")
        retry = self.engine().retry_failed()
        self.assertEqual(retry.state["nodes"]["left"]["retry_from"], second["nodes"]["left"]["workspace"])
        self.assertEqual(len(retry.state["nodes"]["left"]["attempt_history"]), 2)

        def final_worker(backend, model, cwd, prompt, timeout, **kwargs):
            if self.assignment(prompt) == "left":
                self.assertEqual((cwd / "left.txt").read_text(), "second draft")
                self.assertIn("Second attempt still lacks", prompt)
            return {"content": "Verified", "data": {}, "checks": []}

        with patch("runtime.coding.run_coding_task", side_effect=final_worker):
            third = retry.run()
        self.assertEqual(third["status"], "waiting_review")
        self.assertEqual(third["nodes"]["left"]["attempts"], 3)
        self.assertEqual((second_work / "left.txt").read_text(), "second draft")

    def test_old_state_without_workspace_uses_legacy_work_directory(self):
        failed = self.fail_run()
        original_work = failed["nodes"]["left"].pop("workspace")
        self.save_state(failed)
        retry = self.engine().retry_failed()
        self.assertEqual(retry.state["nodes"]["left"]["retry_from"], original_work)
        with patch("runtime.coding.run_coding_task", side_effect=self.completed_worker):
            state = retry.run()
        self.assertEqual(state["status"], "waiting_review")

    def test_failure_before_workspace_creation_can_retry_without_a_draft(self):
        prepare = LocalWorkspace.prepare

        def fail_prepare(space, node, inputs, **kwargs):
            if node["id"] == "left":
                raise ValueError("temporary materialization problem")
            return prepare(space, node, inputs, **kwargs)

        with patch.object(LocalWorkspace, "prepare", fail_prepare), patch("runtime.coding.run_coding_task", side_effect=self.initial_worker):
            state = self.engine().run()
        self.assertEqual(state["status"], "failed")
        self.assertNotIn("workspace", state["nodes"]["left"])
        retry = self.engine().retry_failed()
        self.assertIsNone(retry.state["nodes"]["left"]["retry_from"])

        def worker(backend, model, cwd, prompt, timeout, **kwargs):
            if self.assignment(prompt) == "left":
                self.assertFalse((cwd / "left.txt").exists())
                (cwd / "left.txt").write_text("new work", encoding="utf-8")
            return {"content": "Verified", "data": {}, "checks": []}

        with patch("runtime.coding.run_coding_task", side_effect=worker):
            self.assertEqual(retry.run()["status"], "waiting_review")

    def test_unsafe_saved_states_are_rejected_without_backup_or_mutation(self):
        original = self.fail_run()
        for problem in ("hash", "mode", "execution", "status", "running", "rejected_review", "failed_output", "successful_descendant", "missing_result", "sibling_workspace", "missing_workspace"):
            with self.subTest(problem=problem):
                state = copy.deepcopy(original)
                if problem in ("hash", "mode", "execution", "status"):
                    key = {"hash": "workflow_hash", "mode": "mode", "execution": "execution", "status": "status"}[problem]
                    state[key] = "changed"
                elif problem == "running":
                    state["nodes"]["join"]["status"] = "running"
                elif problem == "rejected_review":
                    state["nodes"]["review"].update(status="failed", decision="reject")
                elif problem == "failed_output":
                    state["nodes"]["output"]["status"] = "failed"
                elif problem == "successful_descendant":
                    state["nodes"]["join"]["status"] = "succeeded"
                    state["results"]["join"] = {"content": "stale"}
                elif problem == "sibling_workspace":
                    state["nodes"]["left"]["workspace"] = state["nodes"]["right"]["workspace"]
                elif problem == "missing_workspace":
                    state["nodes"]["left"]["workspace"] = ".knot/tasks/task-003-left/missing/work"
                else:
                    del state["results"]["right"]
                self.save_state(state)
                before = (self.root / "logs/run-state.json").read_bytes()
                with self.assertRaises(ValueError):
                    self.engine().retry_failed()
                self.assertEqual((self.root / "logs/run-state.json").read_bytes(), before)
                self.assertEqual(list((self.root / "logs").glob("*.before-retry-*.json")), [])

    def test_retry_rejects_nonlocal_mode_and_missing_saved_state(self):
        with self.assertRaisesRegex(ValueError, "only in local"):
            Engine(self.flow, self.root, "mock").retry_failed()
        with self.assertRaises(FileNotFoundError):
            self.engine().retry_failed()

    def test_cli_retry_is_explicit_and_does_not_change_saved_execution(self):
        self.fail_run()
        (self.root / "workflow.json").write_text(json.dumps(self.flow), encoding="utf-8")
        save_execution(self.root, EXECUTION)
        before_config = (self.root / "knot.json").read_bytes()
        before_state = (self.root / "logs/run-state.json").read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch("sys.stdin.isatty", return_value=False), \
                patch("run.check_backend", return_value={"available": True}), patch("runtime.coding.run_coding_task") as worker:
            code = run.main(["--root", str(self.root), "--retry-failed", "--model", "changed"])
        self.assertEqual(code, 1)
        self.assertIn("Execution settings changed", err.getvalue())
        worker.assert_not_called()
        self.assertEqual((self.root / "knot.json").read_bytes(), before_config)
        self.assertEqual((self.root / "logs/run-state.json").read_bytes(), before_state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch("sys.stdin.isatty", return_value=False), patch("run.check_backend", return_value={"available": True}), \
                patch("runtime.coding.run_coding_task", side_effect=self.completed_worker):
            self.assertEqual(run.main(["--root", str(self.root), "--retry-failed", "--plain"]), 2)
        self.assertEqual(self.read_state()["nodes"]["review"]["status"], "waiting_review")

    def test_cli_rejects_conflicting_retry_flags_before_starting(self):
        for flags in (("--mode", "mock"), ("--resume",), ("--configure",), ("--validate",)):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()), patch("run.Engine") as engine:
                with self.assertRaises(SystemExit) as raised:
                    run.main(["--root", str(self.root), "--retry-failed", *flags])
                self.assertEqual(raised.exception.code, 2)
                engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
