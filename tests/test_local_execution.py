"""Local worker orchestration and real source-file handoffs; no model calls."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runtime.engine import Engine
from runtime.validation import validate_workflow
from runtime.security import safe_path
from runtime.workspace import LocalWorkspace
from tests.test_runtime import workflow, edge


EXECUTION = {"schema_version": "1.0", "backend": "codex", "model": "shared-model", "task_timeout_seconds": 60}


class LocalExecutionTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="local-workspace-", dir=scratch)
        self.root = Path(self.temp.name)
        self.calls = []
        self.call_lock = threading.Lock()

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, flow, execution=None):
        return Engine(flow, self.root, "local", execution=execution or EXECUTION)

    def worker(self, backend, model, cwd, prompt, timeout, *, event_callback=None, usage_callback=None):
        assignment = json.loads(prompt.split("Assigned work:\n", 1)[1])
        task = assignment["task"]["id"]
        with self.call_lock:
            self.calls.append((task, backend, model, cwd))
        self.assertTrue((cwd / ".knot-context/input-data.json").exists())
        if task in ("left", "right"):
            time.sleep(0.08)
            (cwd / (task + ".py")).write_text(f"value = {2 if task == 'left' else 3}\n", encoding="utf-8")
        elif task == "join":
            self.assertTrue((cwd / "left.py").is_file())
            self.assertTrue((cwd / "right.py").is_file())
            (cwd / "main.py").write_text("from left import value as a\nfrom right import value as b\nprint(a + b)\n", encoding="utf-8")
            checked = subprocess.run([sys.executable, "main.py"], cwd=cwd, capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.stdout.strip(), "5")
            self.assertEqual(checked.returncode, 0)
        return {"content": f"Completed {task}", "data": {"task": task}, "session_id": task + "-session", "checks": []}

    def test_one_backend_and_model_runs_parallel_roles_and_delivers_code(self):
        flow = workflow(False)
        self.assertEqual(validate_workflow(flow, "local"), [])
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            state = self.engine(flow).run()
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(c[1:3] == ("codex", "shared-model") for c in self.calls))
        self.assertEqual(len({c[3] for c in self.calls}), 3)
        left, right = state["nodes"]["left"], state["nodes"]["right"]
        self.assertLess(max(left["started_at"], right["started_at"]), min(left["finished_at"], right["finished_at"]))
        delivered = self.root / "results/project"
        result = subprocess.run([sys.executable, "main.py"], cwd=delivered, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.stdout.strip(), "5")
        self.assertEqual({p.name for p in delivered.iterdir()} - {"__pycache__"}, {"left.py", "right.py", "main.py"})
        self.assertNotIn(".knot-context", [p.name for p in delivered.iterdir()])
        self.assertEqual(state["results"]["join"]["mode"], "local")
        self.assertEqual(state["execution"], EXECUTION)

    def test_review_pauses_source_delivery_and_resume_does_not_rerun_workers(self):
        flow = workflow(True)
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            before = self.engine(flow).run()
            self.assertEqual(before["status"], "waiting_review")
            self.assertFalse((self.root / "results/project").exists())
            changed = {**EXECUTION, "model": "another-model"}
            with self.assertRaisesRegex(ValueError, "Execution settings changed"):
                self.engine(flow, changed).resume("review", "approve", "member")
            state = self.engine(flow).resume("review", "approve", "member").run()
        self.assertEqual(state["status"], "completed", {k: v for k, v in state["nodes"].items() if v.get("error")})
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(before["nodes"]["join"], state["nodes"]["join"])

    def test_rejected_review_never_publishes_project(self):
        flow = workflow(True)
        with patch("runtime.coding.run_coding_task", side_effect=self.worker):
            self.engine(flow).run()
            state = self.engine(flow).resume("review", "reject", "member").run()
        self.assertEqual(state["status"], "failed")
        self.assertFalse((self.root / "results/project").exists())

    def test_control_dependencies_do_not_copy_code(self):
        flow = workflow(False)
        flow["edges"] = [e for e in flow["edges"] if not (e["target"] == "join" and e["kind"] == "data")]
        def worker(backend, model, cwd, prompt, timeout, **kwargs):
            task = json.loads(prompt.split("Assigned work:\n", 1)[1])["task"]["id"]
            if task == "join":
                self.assertFalse((cwd / "left.py").exists())
                self.assertFalse((cwd / "right.py").exists())
                return {"content": "No upstream source", "data": {}}
            return self.worker(backend, model, cwd, prompt, timeout, **kwargs)
        with patch("runtime.coding.run_coding_task", side_effect=worker):
            state = self.engine(flow).run()
        self.assertEqual(state["status"], "completed")
        self.assertFalse((self.root / "results/project/left.py").exists())

    def test_parallel_file_conflicts_stop_before_next_agent(self):
        def conflict(backend, model, cwd, prompt, timeout, **kwargs):
            task = json.loads(prompt.split("Assigned work:\n", 1)[1])["task"]["id"]
            self.calls.append(task)
            (cwd / "shared.py").write_text(task, encoding="utf-8")
            return {"content": task, "data": {}}
        with patch("runtime.coding.run_coding_task", side_effect=conflict):
            state = self.engine(workflow(False)).run()
        self.assertEqual(state["status"], "failed")
        self.assertIn("Source conflict", state["nodes"]["join"]["error"])
        self.assertNotIn("join", self.calls)
        self.assertFalse((self.root / "results/project").exists())

    def test_failed_coding_task_is_not_automatically_replayed(self):
        flow = workflow(False)
        flow["limits"]["max_retries"] = 3
        with patch("runtime.coding.run_coding_task", side_effect=RuntimeError("Authentication failed")) as worker:
            state = self.engine(flow).run()
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(state["nodes"]["left"]["attempts"], 1)
        self.assertEqual(state["nodes"]["join"]["status"], "blocked")
        self.assertFalse((self.root / "results/project").exists())

    def test_seed_sources_and_deletions_are_preserved_without_credentials(self):
        seed = self.root / "workspace"
        seed.mkdir()
        (seed / "old.py").write_text("old", encoding="utf-8")
        (seed / ".env").write_text("KNOT_TEST=private", encoding="utf-8")
        flow = workflow(False)
        space = LocalWorkspace(self.root, flow)
        left = next(n for n in flow["nodes"] if n["id"] == "left")
        join = next(n for n in flow["nodes"] if n["id"] == "join")
        work, before, inherited = space.prepare(left, {})
        self.assertFalse((work / ".env").exists())
        (work / "old.py").unlink()
        (work / "new.py").write_text("new", encoding="utf-8")
        changes, modified = space.collect(left, work, before, inherited)
        self.assertEqual(set(modified), {"old.py", "new.py"})
        work2, _, _ = space.prepare(join, {"left": {"artifacts": changes}})
        self.assertFalse((work2 / "old.py").exists())
        self.assertEqual((work2 / "new.py").read_text(), "new")

    def test_latest_data_descendant_wins_over_its_ancestor(self):
        flow = workflow(False)
        space = LocalWorkspace(self.root, flow)
        first = {"a.py": {"hash": "a" * 64, "node": "left"}}
        newer = {"a.py": {"hash": "b" * 64, "node": "join", "supersedes": ["left"]}}
        self.assertEqual(space.merge({"newer": {"artifacts": newer}, "old": {"artifacts": first}}), newer)
        self.assertEqual(space.merge({"old": {"artifacts": first}, "newer": {"artifacts": newer}}), newer)

    def test_static_data_path_without_actual_handoff_does_not_authorize_overwrite(self):
        # A dependency may be skipped at runtime. The graph alone is not proof
        # that a task based its edits on an upstream version of this file.
        space = LocalWorkspace(self.root, workflow(False))
        first = {"a.py": {"hash": "a" * 64, "node": "left", "supersedes": []}}
        independent = {"a.py": {"hash": "b" * 64, "node": "join", "supersedes": []}}
        with self.assertRaisesRegex(ValueError, "Source conflict"):
            space.merge({"old": {"artifacts": first}, "unrelated": {"artifacts": independent}})

    def test_identical_parallel_edits_retain_both_origins_for_later_changes(self):
        space = LocalWorkspace(self.root, workflow(False))
        left = {"same.py": {"hash": "a" * 64, "node": "left"}}
        right = {"same.py": {"hash": "a" * 64, "node": "right"}}
        inherited = space.merge({"left": {"artifacts": left}, "right": {"artifacts": right}})
        self.assertEqual(set(inherited["same.py"]["supersedes"]) | {inherited["same.py"]["node"]}, {"left", "right"})
        final = {"same.py": {"hash": "b" * 64, "node": "join", "supersedes": ["left", "right"]}}
        self.assertEqual(space.merge({"final": {"artifacts": final}, "left": {"artifacts": left}, "right": {"artifacts": right}}), final)

    def test_reserved_project_output_is_rejected_for_local_mode(self):
        flow = workflow(False)
        flow["nodes"][-1]["config"]["mappings"][0]["filename"] = "project/main.py"
        self.assertIn("output_path", [i["code"] for i in validate_workflow(flow, "local")])

    def test_seed_artifact_hash_is_checked_on_review_resume(self):
        space = LocalWorkspace(self.root, workflow(False))
        space.initialize()
        digest = space._put(b"original")
        space._blob(digest).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "modified"):
            space._read(digest)

    @unittest.skipUnless(os.name == "nt", "Windows extended path regression")
    def test_windows_resolved_extended_prefix_stays_inside_workspace(self):
        target = self.root / "workspace" / "module.py"
        target.parent.mkdir()
        target.write_text("value = 1", encoding="utf-8")
        original = Path.resolve
        def extended(path, *args, **kwargs):
            resolved = original(path, *args, **kwargs)
            return Path("\\\\?\\" + str(resolved)) if path == target else resolved
        with patch.object(Path, "resolve", extended):
            self.assertEqual(safe_path(self.root, "workspace/module.py", ("workspace",)), target)


if __name__ == "__main__":
    unittest.main()
