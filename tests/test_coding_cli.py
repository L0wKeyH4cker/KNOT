"""Exercise the actual subprocess transport with deterministic CLI stand-ins."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from runtime.coding import _arguments, _command, cancel_all, check_backend, reset_cancellation, run_coding_task


class CodingCLITests(unittest.TestCase):
    def setUp(self):
        reset_cancellation()
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="coding-cli-", dir=scratch)
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        reset_cancellation()
        self.temp.cleanup()

    def script(self, body):
        script = self.root / "fake_cli.py"
        script.write_text("import sys, json, os, time\nfrom pathlib import Path\nsys.stdin.reconfigure(encoding='utf-8')\nsys.stdout.reconfigure(encoding='utf-8')\n" + body, encoding="utf-8")
        return [sys.executable, str(script)]

    def call(self, backend, body, **kwargs):
        command = self.script(body)
        with patch("runtime.coding._command", return_value=command):
            return run_coding_task(backend, kwargs.pop("model", ""), self.root,
                                   kwargs.pop("prompt", "Implement the assigned task"),
                                   kwargs.pop("timeout", 5), **kwargs)

    def test_codex_reads_unicode_prompt_from_stdin_and_returns_actual_artifacts(self):
        events = []
        result = self.call("codex", r'''
request = sys.stdin.read()
Path('request.txt').write_text(request, encoding='utf-8')
Path('argv.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
Path('app.py').write_text('print(42)\n', encoding='utf-8')
print(json.dumps({'type': 'thread.started', 'thread_id': 'session-a'}))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'exit_code': 0}}))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'status': 'completed', 'content': 'Created app.py', 'data': {'file': 'app.py'}, 'checks': ['python app.py']})}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 12}}))
''', prompt="实现中文页面 `literal` $(no-shell) & untouched", model="one-shared-model", event_callback=events.append)
        self.assertEqual(result["session_id"], "session-a")
        self.assertEqual(result["data"], {"file": "app.py"})
        self.assertEqual(result["usage"]["input_tokens"], 12)
        self.assertTrue((self.root / "app.py").exists())
        self.assertIn("实现中文页面 `literal` $(no-shell) & untouched", (self.root / "request.txt").read_text(encoding="utf-8"))
        args = json.loads((self.root / "argv.json").read_text())
        self.assertEqual(args[args.index("--model") + 1], "one-shared-model")
        self.assertEqual(args[args.index("--sandbox") + 1], "workspace-write")
        self.assertNotIn("Implement", " ".join(args))
        self.assertIn({"backend": "codex", "event": "item.completed", "item_type": "command_execution", "exit_code": 0, "session_id": "session-a"}, events)

    def test_claude_parses_structured_output_and_uses_shared_model(self):
        result = self.call("claude", r'''
sys.stdin.read()
Path('argv.json').write_text(json.dumps(sys.argv[1:]))
print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'claude-a'}))
print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 'claude-a', 'structured_output': {'status': 'completed', 'content': 'Implemented', 'data': [{'name': 'row'}], 'checks': []}, 'usage': {'output_tokens': 4}}))
''', model="my-model")
        self.assertEqual(result["data"], [{"name": "row"}])
        self.assertEqual(result["session_id"], "claude-a")
        args = json.loads((self.root / "argv.json").read_text())
        self.assertEqual(args[args.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(args[args.index("--model") + 1], "my-model")
        self.assertNotIn("--dangerously-skip-permissions", args)

    def test_zero_exit_without_terminal_event_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "without a successful terminal"):
            self.call("codex", "sys.stdin.read()\nprint(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Done'}}))\n")

    def test_terminal_success_still_requires_structured_completion(self):
        with self.assertRaisesRegex(RuntimeError, "invalid completion record"):
            self.call("codex", "sys.stdin.read()\nprint(json.dumps({'type':'turn.completed'}))\n")

    def test_agent_can_report_blocked_even_after_cli_success(self):
        with self.assertRaisesRegex(RuntimeError, "blocked: Missing dependency"):
            self.call("claude", "sys.stdin.read()\nprint(json.dumps({'type':'result','subtype':'success','structured_output':{'status':'blocked','content':'Missing dependency','data':{}}}))\n")

    def test_claude_errors_and_permissions_are_not_hidden_by_exit_zero(self):
        for event in ({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Not authenticated"},
                      {"type": "result", "subtype": "success", "permission_denials": [{"tool_name": "Bash"}],
                       "structured_output": {"status": "completed", "content": "Done", "data": {}}}):
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                self.call("claude", "sys.stdin.read()\nprint(" + repr(json.dumps(event)) + ")\n")

    def test_codex_turn_failed_surfaces_authentication_error(self):
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self.call("codex", "sys.stdin.read()\nprint(json.dumps({'type':'turn.failed','error':{'message':'Authentication expired'}}))\n")

    def test_stderr_secrets_are_redacted(self):
        secret = "a-registered-local-token-value"
        with patch.dict(os.environ, {"KNOT_TEST_TOKEN": secret}):
            with self.assertRaises(RuntimeError) as caught:
                self.call("codex", "sys.stdin.read()\nprint(os.environ['KNOT_TEST_TOKEN'], file=sys.stderr)\nsys.exit(2)\n")
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_timeout_stops_child_commands(self):
        with self.assertRaises(TimeoutError):
            self.call("codex", r'''
import subprocess
sys.stdin.read()
subprocess.Popen([sys.executable, '-c', "import time; from pathlib import Path; time.sleep(1.5); Path('orphan.txt').write_text('bad')"])
print(json.dumps({'type': 'thread.started', 'thread_id': 'slow'}), flush=True)
time.sleep(10)
''', timeout=0.5)
        time.sleep(1.6)
        self.assertFalse((self.root / "orphan.txt").exists(), "A timed-out task left its child command alive")

    def test_oversized_event_stops_task(self):
        with patch("runtime.coding.MAX_LINE_BYTES", 100), self.assertRaisesRegex(RuntimeError, "oversized"):
            self.call("codex", "sys.stdin.read()\nprint('x' * 500)\n")

    def test_backend_check_never_runs_a_task(self):
        command = self.script("assert sys.argv[1:] == ['--version']\nprint('codex-cli 1.0')\n")
        with patch("runtime.coding._command", return_value=command):
            result = check_backend("codex")
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "codex-cli 1.0")
        with patch("runtime.coding.shutil.which", return_value=None):
            missing = check_backend("claude")
        self.assertFalse(missing["available"])
        self.assertIn("PATH", missing["message"])

    def test_npm_cmd_wrapper_is_resolved_without_shell(self):
        shim = self.root / "codex.cmd"
        shim.write_text("not parsed or executed")
        package = self.root / "node_modules/@openai/codex"
        (package / "bin").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"bin": {"codex": "bin/codex.js"}}))
        (package / "bin/codex.js").write_text("// fixture")
        with patch("runtime.coding.shutil.which", side_effect=lambda name: str(shim) if name == "codex" else sys.executable):
            command = _command("codex")
        self.assertEqual(command, [sys.executable, str(package / "bin/codex.js")])

    def test_malformed_npm_wrapper_is_rejected(self):
        shim = self.root / "claude.cmd"
        shim.write_text("never execute this shell wrapper")
        with patch("runtime.coding.shutil.which", return_value=str(shim)), self.assertRaisesRegex(RuntimeError, "wrapper safely"):
            _command("claude")

    def test_default_model_uses_cli_configuration_without_per_role_models(self):
        for backend in ("codex", "claude"):
            self.assertNotIn("--model", _arguments(backend, ""))
        with self.assertRaises(ValueError):
            _arguments("codex", "model\n--bad-flag")

    def test_cancel_stops_running_and_prevents_pending_tasks(self):
        errors = []
        command = self.script("sys.stdin.read()\nPath('started').touch()\ntime.sleep(20)\n")
        def worker():
            try:
                run_coding_task("codex", "", self.root, "work", 25)
            except RuntimeError as error:
                errors.append(str(error))
        with patch("runtime.coding._command", return_value=command):
            thread = threading.Thread(target=worker)
            thread.start()
            deadline = time.monotonic() + 5
            while not (self.root / "started").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.root / "started").exists())
            cancel_all()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(errors)
            with self.assertRaisesRegex(RuntimeError, "cancelled before launch"):
                run_coding_task("codex", "", self.root, "queued work", 5)


if __name__ == "__main__":
    unittest.main()
