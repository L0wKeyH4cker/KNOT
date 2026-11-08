"""Discover concurrent local runs without reading arbitrary folders or secrets."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime.registry import RunRegistration, default_registry_dir, list_runs, MAX_STATE_BYTES


class RunRegistryTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="run-registry-", dir=scratch)
        self.root = Path(self.temporary.name)
        self.registry = self.root / "registry"

    def tearDown(self):
        self.temporary.cleanup()

    def run_folder(self, name="project-a", *, status="running", run_id=None):
        folder = self.root / name
        (folder / "logs").mkdir(parents=True)
        state = {"run_id": run_id or name + "-run", "mode": "local", "status": status,
                 "project": {"id": name, "name": name},
                 "execution": {"backend": "codex", "model": "shared-model"},
                 "started_at": "2026-11-07T15:00:00+00:00", "updated_at": "2026-11-07T15:00:05+00:00",
                 "nodes": {"task-a": {"label": "Write the API", "type": "agent_task", "agent_name": "Backend developer", "status": "running",
                                            "activity": {"kind": "command", "text": "python -m unittest", "status": "running"},
                                            "last_activity_at": "2026-11-07T15:00:05+00:00"}},
                 "results": {"secret-source": {"content": "private original requirements"}}}
        (folder / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
        return folder, state

    def write_state(self, folder, state):
        (folder / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")

    def registration(self, folder, state, **kwargs):
        return RunRegistration(folder, folder / "logs/run-state.json", state["run_id"], self.registry, **kwargs)

    def test_override_registry_directory_is_respected_without_creating_it(self):
        with patch.dict(os.environ, {"KNOT_RUNS_DIR": str(self.registry)}):
            self.assertEqual(default_registry_dir(), self.registry)
            self.assertEqual(list_runs(), [])
        self.assertFalse(self.registry.exists())

    def test_separate_registrations_discover_concurrent_projects(self):
        a, state_a = self.run_folder("a")
        b, state_b = self.run_folder("b")
        with self.registration(a, state_a), self.registration(b, state_b):
            entries = list_runs(self.registry)
            self.assertEqual({r["project"]["name"] for r in entries}, {"a", "b"})
            self.assertTrue(all(r["live"] for r in entries))
            self.assertTrue(all(r["display_status"] == "running" for r in entries))
            self.assertEqual(len(list(self.registry.glob("*.json"))), 2)
        self.assertTrue(all(not r["live"] for r in list_runs(self.registry)))

    def test_heartbeat_updates_while_work_has_no_new_events(self):
        folder, state = self.run_folder()
        with self.registration(folder, state, heartbeat_interval=0.05) as registration:
            before = json.loads((self.registry / registration.filename).read_text())["heartbeat_at"]
            deadline = time.monotonic() + 2
            after = before
            while after == before and time.monotonic() < deadline:
                time.sleep(0.03)
                after = json.loads((self.registry / registration.filename).read_text())["heartbeat_at"]
            self.assertNotEqual(before, after)
            self.assertEqual(list_runs(self.registry)[0]["updated_at"], state["updated_at"])

    def test_stale_run_is_disconnected_and_not_fabricated_as_complete(self):
        folder, state = self.run_folder()
        registration = self.registration(folder, state)
        registration.start()
        registration.close()
        path = self.registry / registration.filename
        record = json.loads(path.read_text())
        record.update(active=True, heartbeat_at="2020-01-01T00:00:00+00:00")
        path.write_text(json.dumps(record), encoding="utf-8")
        snapshot = list_runs(self.registry)[0]
        self.assertFalse(snapshot["live"])
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["display_status"], "disconnected")

    def test_closed_review_and_completed_runs_keep_their_real_status(self):
        for status in ("waiting_review", "completed"):
            folder, state = self.run_folder(status, status=status)
            with self.registration(folder, state):
                pass
        snapshots = list_runs(self.registry)
        self.assertEqual({s["display_status"] for s in snapshots}, {"waiting_review", "completed"})
        self.assertFalse(any(s["live"] for s in snapshots))

    def test_explicit_legacy_root_uses_workflow_labels_without_registration(self):
        folder, state = self.run_folder()
        state.pop("project")
        state["nodes"]["task-a"] = {"status": "running"}
        self.write_state(folder, state)
        workflow = {"project": {"name": "Legacy project"}, "agents": [{"id": "writer", "name": "Writer"}],
                    "nodes": [{"id": "task-a", "label": "Build module", "type": "agent_task", "config": {"agent_id": "writer"}}]}
        (folder / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")
        snapshot = list_runs(self.registry, roots=[folder])[0]
        self.assertEqual(snapshot["project"]["name"], "Legacy project")
        self.assertEqual(snapshot["nodes"]["task-a"]["agent_name"], "Writer")
        self.assertEqual(snapshot["nodes"]["task-a"]["label"], "Build module")
        self.assertEqual(snapshot["display_status"], "disconnected")

    def test_explicit_root_does_not_replace_live_registered_snapshot(self):
        folder, state = self.run_folder()
        with self.registration(folder, state):
            entries = list_runs(self.registry, roots=[folder, folder])
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0]["live"])

    def test_small_progress_file_is_used_without_reading_large_full_state(self):
        folder, state = self.run_folder()
        full = folder / "logs/run-state.json"
        full.write_bytes(b"x" * (MAX_STATE_BYTES + 1))
        progress = folder / "logs/run-state.progress.json"
        progress.write_text(json.dumps({k: v for k, v in state.items() if k != "results"}), encoding="utf-8")
        with self.registration(folder, state):
            snapshot = list_runs(self.registry)[0]
        self.assertEqual(snapshot["run_id"], state["run_id"])
        self.assertNotIn("results", snapshot)

    def test_stale_progress_file_falls_back_to_current_state(self):
        folder, state = self.run_folder()
        old = {**state, "run_id": "old-run", "status": "completed"}
        progress = folder / "logs/run-state.progress.json"
        progress.write_text(json.dumps(old), encoding="utf-8")
        os.utime(progress, (1, 1))
        with self.registration(folder, state):
            snapshot = list_runs(self.registry)[0]
        self.assertEqual(snapshot["run_id"], state["run_id"])
        self.assertEqual(snapshot["status"], "running")

    def test_corrupt_and_partial_files_do_not_break_other_runs(self):
        folder, state = self.run_folder()
        self.registry.mkdir()
        (self.registry / "corrupt.json").write_text("{bad", encoding="utf-8")
        (self.registry / "incomplete.json.tmp").write_text("{", encoding="utf-8")
        with self.registration(folder, state):
            self.assertEqual(len(list_runs(self.registry)), 1)

    def test_old_registration_cannot_claim_a_reused_folder(self):
        folder, state = self.run_folder()
        with self.registration(folder, state):
            state["run_id"] = "new-run"
            self.write_state(folder, state)
            self.assertEqual(list_runs(self.registry), [])
            explicit = list_runs(self.registry, roots=[folder])
            self.assertEqual(explicit[0]["run_id"], "new-run")
            self.assertFalse(explicit[0]["live"])

    def test_registry_refuses_state_paths_outside_logs(self):
        folder, state = self.run_folder()
        self.registry.mkdir()
        record = {"schema_version": "1.0", "root": str(folder), "state_path": str(folder / "workflow.json"), "run_id": state["run_id"], "active": True}
        (self.registry / "bad.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(list_runs(self.registry), [])
        with self.assertRaises(ValueError):
            RunRegistration(folder, "../outside.json", state["run_id"], self.registry)

    def test_display_snapshot_excludes_results_raw_tool_args_and_credentials(self):
        folder, state = self.run_folder()
        state["nodes"]["task-a"]["activity"]["text"] = "curl --api-key=private-value\x1b[2J"
        state["last_events"] = [{"time": "now", "event": "coding_event", "node_id": "task-a",
                                 "detail": {"activity": {"kind": "command", "text": "Authorization: Bearer private-token"},
                                            "raw_input": "do-not-display", "reasoning": "do-not-display"}}]
        self.write_state(folder, state)
        snapshot = list_runs(self.registry, roots=[folder])[0]
        rendered = json.dumps(snapshot)
        self.assertNotIn("private original requirements", rendered)
        self.assertNotIn("private-value", rendered)
        self.assertNotIn("private-token", rendered)
        self.assertNotIn("do-not-display", rendered)
        self.assertNotIn("\\u001b", rendered)

    def test_unwritable_registration_does_not_stop_run_and_reports_once(self):
        folder, state = self.run_folder()
        self.registry.write_text("not a directory", encoding="utf-8")
        with self.registration(folder, state, heartbeat_interval=0.05) as registration:
            time.sleep(0.12)
        self.assertEqual(len(registration.warnings), 1)
        self.assertIn("discovery is unavailable", registration.warning)
        self.assertTrue((folder / "logs/run-state.json").exists())

    def test_close_is_idempotent_and_leaves_no_temporary_files(self):
        folder, state = self.run_folder()
        registration = self.registration(folder, state).start()
        registration.close()
        registration.close()
        self.assertEqual(len(list(self.registry.glob("*.json"))), 1)
        self.assertEqual(list(self.registry.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
