"""Provider event fixtures exercise live telemetry without contacting an API."""
import json
import os
import unittest
from unittest.mock import patch

from runtime.activity import sanitize_text
from runtime.coding import _Transcript


class ActivitySanitizerTests(unittest.TestCase):
    def test_terminal_controls_and_bidi_cannot_change_display(self):
        value = "检查\x1b[31m文件\x1b[0m\x1b]52;c;clipboard-secret\x07\x1b]8;;https://evil\x1b\\link\x1b]8;;\x1b\\\n第二行\u202e\u2066\x00\x9b2J"
        self.assertEqual(sanitize_text(value), "检查文件link 第二行")
        self.assertEqual(sanitize_text("safe\x1b]unfinished attack"), "safe")
        self.assertEqual(sanitize_text("safe\x1bPhidden\x1b\\ visible"), "safe visible")

    def test_registered_environment_and_generic_credentials_are_masked(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "local-secret-value", "TEST_PASSWORD": "local-password-value"}):
            text = sanitize_text("echo local-secret-value local-password-value", 1000)
            self.assertNotIn("local-secret-value", text)
            self.assertNotIn("local-password-value", text)
        cases = [
            ("curl -H 'Authorization: Bearer independent-secret'", "independent-secret"),
            ("OPENAI_API_KEY=independent-secret python run.py", "independent-secret"),
            ("$env:API_KEY = 'a password with spaces'", "a password with spaces"),
            ('{"api_key": "independent-secret"}', "independent-secret"),
            ("tool --password independent-secret", "independent-secret"),
            ("PASSWORD='independent-secret'", "independent-secret"),
            ("curl https://user:" + "independent-secret" + "@example.test/", "independent-secret"),
            ("Authorization: Basic independent-secret", "independent-secret"),
        ]
        for value, secret in cases:
            with self.subTest(value=value):
                actual = sanitize_text(value, 1000)
                self.assertNotIn(secret, actual)
                self.assertIn("[REDACTED]", actual)

    def test_strip_control_characters_before_matching_secret_and_clip_after_masking(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "very-sensitive-token"}):
            self.assertEqual(sanitize_text("very-\x1b[31msensitive-token"), "[REDACTED]")
        self.assertNotIn("longsecret", sanitize_text("API_KEY=" + "longsecret" * 30, 25))
        self.assertEqual(len(sanitize_text("长" * 301)), 300)
        self.assertEqual(sanitize_text("abc", 0), "")
        self.assertEqual(sanitize_text(None), "")


class ActivityTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.events = []

    def send(self, transcript, event):
        transcript.line(json.dumps(event, ensure_ascii=False).encode("utf-8"))

    def test_codex_emits_command_start_before_completion_and_never_stdout(self):
        transcript = _Transcript("codex", self.events.append)
        self.send(transcript, {"type": "thread.started", "thread_id": "session-a"})
        command = "python build.py --api-key independent-secret"
        self.send(transcript, {"type": "item.started", "item": {"id": "cmd1", "type": "command_execution", "command": command, "status": "in_progress"}})
        self.assertFalse(transcript.finished)
        activity = self.events[-1]["activity"]
        self.assertEqual(activity["kind"], "command")
        self.assertEqual(activity["status"], "running")
        self.assertEqual(self.events[-1]["session_id"], "session-a")
        self.assertNotIn("independent-secret", activity["text"])
        self.send(transcript, {"type": "item.completed", "item": {"id": "cmd1", "type": "command_execution", "command": command, "exit_code": 1, "aggregated_output": "PRIVATE STDOUT", "status": "completed"}})
        self.assertEqual(self.events[-1]["activity"]["status"], "failed")
        self.assertEqual(self.events[-1]["activity"]["exit_code"], 1)
        self.assertNotIn("PRIVATE STDOUT", json.dumps(self.events))

    def test_codex_files_and_public_summary_exclude_patch_and_private_data(self):
        transcript = _Transcript("codex", self.events.append)
        self.send(transcript, {"type": "item.completed", "item": {"type": "file_change", "status": "completed", "changes": [{"path": "src/页面.tsx", "kind": "add", "diff": "PRIVATE PATCH"}]}})
        self.assertEqual(self.events[-1]["activity"]["paths"], ["src/页面.tsx"])
        self.assertEqual(self.events[-1]["activity"]["status"], "completed")
        self.send(transcript, {"type": "item.completed", "item": {"type": "reasoning", "text": "PRIVATE REASONING"}})
        self.assertNotIn("activity", self.events[-1])
        self.send(transcript, {"type": "item.completed", "item": {"type": "agent_message", "text": "Checking 页面.tsx"}})
        self.assertEqual(self.events[-1]["activity"]["text"], "Checking 页面.tsx")
        completion = {"status": "completed", "content": "PRIVATE REPORT", "data": {"private": "PRIVATE DATA"}}
        self.send(transcript, {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(completion)}})
        self.assertNotIn("activity", self.events[-1])
        self.send(transcript, {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 7, "extra": "PRIVATE USAGE"}})
        self.assertEqual(self.events[-1]["usage"], {"input_tokens": 12, "output_tokens": 7})
        for private in ("PRIVATE PATCH", "PRIVATE REASONING", "PRIVATE REPORT", "PRIVATE DATA", "PRIVATE USAGE"):
            self.assertNotIn(private, json.dumps(self.events))
        self.assertEqual(transcript.result()["data"], completion["data"])

    def test_claude_multiple_tools_emit_immediately_then_correlate_results(self):
        transcript = _Transcript("claude", self.events.append)
        self.send(transcript, {"type": "assistant", "session_id": "claude-a", "message": {"content": [
            {"type": "thinking", "thinking": "PRIVATE REASONING"},
            {"type": "tool_use", "id": "bash1", "name": "Bash", "input": {"command": "python check.py", "description": "PRIVATE DESCRIPTION"}},
            {"type": "tool_use", "id": "write1", "name": "Write", "input": {"file_path": "src/页面.py", "content": "PRIVATE FILE"}},
        ]}})
        self.assertEqual(len(self.events), 2)
        self.assertFalse(transcript.finished)
        self.assertEqual(self.events[0]["activity"]["text"], "python check.py")
        self.assertEqual(self.events[0]["activity"]["status"], "running")
        self.assertEqual(self.events[1]["activity"]["paths"], ["src/页面.py"])
        self.send(transcript, {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "write1", "content": "PRIVATE TOOL RESULT"},
            {"type": "tool_result", "tool_use_id": "bash1", "is_error": True, "content": "PRIVATE STDOUT"},
        ]}})
        self.assertEqual(self.events[-2]["activity"]["tool"], "Write")
        self.assertEqual(self.events[-2]["activity"]["status"], "completed")
        self.assertEqual(self.events[-1]["activity"]["text"], "python check.py")
        self.assertEqual(self.events[-1]["activity"]["status"], "failed")
        self.assertNotIn("exit_code", self.events[-1]["activity"])
        self.assertNotIn("PRIVATE", json.dumps(self.events))

    def test_claude_read_search_unknown_tools_hide_content_and_arguments(self):
        transcript = _Transcript("claude", self.events.append)
        for name, args in [("Read", {"file_path": "app.py"}), ("Grep", {"pattern": "PRIVATE QUERY", "path": "src"}), ("mcp__remote", {"credential": "PRIVATE ARG"})]:
            self.send(transcript, {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": args}]}})
        self.assertEqual(self.events[0]["activity"]["paths"], ["app.py"])
        self.assertEqual(self.events[1]["activity"]["text"], "Grep: searching files")
        self.assertEqual(self.events[2]["activity"]["text"], "mcp__remote")
        self.assertNotIn("PRIVATE", json.dumps(self.events))

    def test_untrusted_metadata_and_partial_json_are_safe(self):
        transcript = _Transcript("codex", self.events.append)
        self.send(transcript, {"type": "thread.started", "thread_id": "id\x1b[2J\u202e"})
        self.assertEqual(self.events[-1]["session_id"], "id")
        self.send(transcript, {"type": "item.updated", "item": {"type": "agent_message", "text": '{"data":"PRIVATE'}})
        self.assertNotIn("activity", self.events[-1])
        self.send(transcript, {"type": "item.updated", "item": {"type": "agent_message", "text": '```json\n{"data":"PRIVATE'}})
        self.assertNotIn("activity", self.events[-1])
        self.send(transcript, {"type": "item.updated", "item": {"type": "command_execution", "command": "pytest", "exit_code": {"private": "PRIVATE"}}})
        self.assertNotIn("exit_code", self.events[-1])
        self.assertNotIn("PRIVATE", json.dumps(self.events))


if __name__ == "__main__":
    unittest.main()
