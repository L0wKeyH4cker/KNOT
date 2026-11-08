"""Observers get safe live progress without becoming a second run-state format."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runtime.engine import Engine
from tests.test_runtime import edge, node, task, workflow


class ProgressTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="progress-", dir=scratch)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def read_progress(self, engine):
        return json.loads(engine.progress_path.read_text(encoding="utf-8"))

    def test_command_activity_is_visible_while_a_silent_task_is_still_running(self):
        flow = workflow(False)
        flow["nodes"] = [node("start", "start"), task("work"), node("output", "output", mappings=[{"source_node": "work", "filename": "report.md", "format": "markdown"}])]
        flow["edges"] = [edge("start", "work"), edge("work", "output"), edge("work", "output", "data")]
        engine = Engine(flow, self.root, "local", execution={"backend": "codex"})
        engine.quiet = True
        allow_event, emitted, release = threading.Event(), threading.Event(), threading.Event()
        outcomes = []

        def fake_cli(*args, event_callback, **kwargs):
            if not allow_event.wait(3):
                raise TimeoutError("Test never allowed activity")
            # A real CLI can emit its first command just after node-start save.
            engine._last_progress_write = time.monotonic()
            event_callback({"backend": "codex", "event": "item.started", "session_id": "test-session", "activity": {"kind": "command", "text": "python check.py", "status": "running"}})
            emitted.set()
            if not release.wait(3):
                raise TimeoutError("Test never released task")
            return {"content": "Done", "data": {}, "checks": []}

        def run():
            try:
                outcomes.append(engine.run())
            except BaseException as error:
                outcomes.append(error)

        with patch("runtime.coding.run_coding_task", side_effect=fake_cli):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if engine.progress_path.exists() and self.read_progress(engine)["nodes"]["work"]["status"] == "running":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("Running task did not publish a snapshot")
                allow_event.set()
                self.assertTrue(emitted.wait(2))
                snapshot = self.read_progress(engine)
                self.assertTrue(worker.is_alive())
                self.assertEqual(snapshot["nodes"]["work"]["status"], "running")
                self.assertEqual(snapshot["nodes"]["work"].get("activity", {}).get("text"), "python check.py")
                self.assertEqual(snapshot["nodes"]["work"]["session_id"], "test-session")
            finally:
                allow_event.set()
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        if isinstance(outcomes[0], BaseException):
            raise outcomes[0]
        self.assertEqual(outcomes[0]["status"], "completed")

    def test_progress_excludes_prompts_results_and_masks_untrusted_display_text(self):
        flow = workflow(False)
        flow["agents"][0]["system_prompt"] = "PRIVATE SYSTEM PROMPT"
        flow["agents"][0]["name"] = "Agent\x1b[2J\u202e"
        flow["project"]["name"] = "Project\x1b]52;c;PRIVATE CLIPBOARD\x07"
        flow["nodes"][2]["label"] = "Build\x1b[31m app\x1b[0m"
        flow["nodes"][2]["config"]["instructions"] = "PRIVATE TASK PROMPT"
        engine = Engine(flow, self.root)
        engine.state["results"]["left"] = {"content": "PRIVATE RESULT CONTENT", "data": {"private": "PRIVATE RESULT DATA"}}
        with patch.dict(os.environ, {"KNOT_PROGRESS_TEST_KEY": "test-hidden-credential"}):
            engine._event("coding_event", "left", detail={"session_id": "session\x1b[2J", "activity": {
                "kind": "command", "status": "running", "text": "python build.py --password unrelated-password test-hidden-credential\x1b[2J",
                "paths": ["src/页面.py\u202e"], "raw": "PRIVATE TOOL PAYLOAD"}})
            engine.state["nodes"]["right"]["error"] = "Failed test-hidden-credential\x1b[31m"
            engine._save()
            snapshot = self.read_progress(engine)
        encoded = json.dumps(snapshot, ensure_ascii=False)
        for private in ("PRIVATE", "test-hidden-credential", "unrelated-password", "\\u001b", "\u202e"):
            self.assertNotIn(private, encoded)
        self.assertNotIn("results", snapshot)
        self.assertNotIn("events", snapshot)
        self.assertEqual(snapshot["nodes"]["left"]["activity"]["paths"], ["src/页面.py"])
        self.assertEqual(snapshot["nodes"]["left"]["session_id"], "session")
        # The authoritative state still has task outputs needed by downstream nodes.
        state = json.loads(engine.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["results"]["left"]["data"], {"private": "PRIVATE RESULT DATA"})

    def test_recent_activity_is_bounded_without_losing_authoritative_events(self):
        engine = Engine(workflow(False), self.root)
        for index in range(85):
            engine._event("coding_event", "left", detail={"activity": {"kind": "command", "text": f"command {index}", "status": "running"}})
        engine._save()
        snapshot = self.read_progress(engine)
        self.assertEqual(len(snapshot["last_events"]), 30)
        self.assertEqual(snapshot["last_events"][0]["activity"]["text"], "command 55")
        self.assertEqual(snapshot["last_events"][-1]["activity"]["text"], "command 84")
        self.assertEqual(len(engine.state["events"]), 85)
        self.assertEqual(len(engine.log_path.read_text(encoding="utf-8").splitlines()), 85)
        self.assertLess(engine.progress_path.stat().st_size, 20000)

    def test_new_activity_flushes_immediately_while_repeated_activity_is_throttled(self):
        engine = Engine(workflow(False), self.root)
        activity = {"kind": "command", "text": "python check.py", "status": "running"}
        with patch("runtime.engine.time.monotonic", return_value=100.0), patch.object(engine, "_save_progress", wraps=engine._save_progress) as save:
            engine._last_progress_write = 100.0
            engine._event("coding_event", "left", detail={"activity": activity})
            self.assertEqual(save.call_count, 1)
            engine._event("coding_event", "left", detail={"activity": activity})
            self.assertEqual(save.call_count, 1)
            engine._event("coding_event", "left", detail={"activity": {**activity, "status": "completed"}})
            self.assertEqual(save.call_count, 2)
            # An independent agent's first activity also appears immediately.
            engine._event("coding_event", "right", detail={"activity": activity})
            self.assertEqual(save.call_count, 3)
        with patch("runtime.engine.time.monotonic", return_value=100.3), patch.object(engine, "_save_progress", wraps=engine._save_progress) as save:
            engine._event("coding_event", "right", detail={"activity": activity})
            self.assertEqual(save.call_count, 1)

    def test_old_review_state_without_progress_fields_resumes(self):
        flow = workflow()
        for item in flow["nodes"]:
            if item["type"] == "agent_task":
                item["config"]["mock_delay_ms"] = 0
        first = Engine(flow, self.root)
        first.run()
        old_state = json.loads(first.state_path.read_text(encoding="utf-8"))
        original_results = copy.deepcopy(old_state["results"])
        old_state.pop("last_events", None)
        old_state.pop("project", None)
        for item in old_state["nodes"].values():
            for key in ("label", "type", "agent_id", "agent_name", "activity", "session_id", "last_activity_at"):
                item.pop(key, None)
        first.state_path.write_text(json.dumps(old_state), encoding="utf-8")
        first.progress_path.unlink()
        resumed = Engine(flow, self.root).resume("review", "approve", "member")
        result = resumed.run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["results"]["left"], original_results["left"])
        self.assertEqual(result["results"]["join"], original_results["join"])
        self.assertEqual(self.read_progress(resumed)["nodes"]["left"]["agent_name"], "Agent")
        self.assertTrue((self.root / "results/report.md").is_file())


if __name__ == "__main__":
    unittest.main()
