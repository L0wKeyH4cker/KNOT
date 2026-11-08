"""OpenCode process/config isolation and optional real-CLI loopback integration."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from runtime.coding import check_backend, reset_cancellation, run_coding_task
from runtime.opencode import OpenCodeTranscript, task_environment


def connection(model="fixture-model", ref="KNOT_ALICE_KEY", base="http://127.0.0.1:9876/v1"):
    return {"provider": "openai", "model": model, "credential_ref": ref,
            "base_url": base, "owner_id": ref, "owner_name": ref}


class OpenCodeTests(unittest.TestCase):
    def setUp(self):
        reset_cancellation()
        self.temp = tempfile.TemporaryDirectory(prefix="knot-opencode-test-")
        self.root = Path(self.temp.name)
        self.key_patch = patch.dict(os.environ, {"KNOT_ALICE_KEY": "fixture-alice-private-key",
                                               "KNOT_BOB_KEY": "fixture-bob-private-key"})
        self.key_patch.start()

    def tearDown(self):
        self.key_patch.stop()
        self.temp.cleanup()
        reset_cancellation()

    def test_each_task_gets_only_its_key_and_private_connection_state(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unrelated-account-key",
                                     "OPENCODE_CONFIG_CONTENT": "untrusted-config"}):
            with task_environment(connection(), self.root) as (alice, alice_model), \
                 task_environment(connection(ref="KNOT_BOB_KEY"), self.root) as (bob, bob_model):
                self.assertEqual(alice["KNOT_TASK_API_KEY"], "fixture-alice-private-key")
                self.assertEqual(bob["KNOT_TASK_API_KEY"], "fixture-bob-private-key")
                self.assertNotEqual(alice["XDG_DATA_HOME"], bob["XDG_DATA_HOME"])
                self.assertNotEqual(alice_model, bob_model)
                self.assertNotIn("OPENAI_API_KEY", alice)
                self.assertNotIn("KNOT_BOB_KEY", alice)
                self.assertNotIn("private-key", alice["OPENCODE_CONFIG_CONTENT"])
                self.assertEqual(os.environ["OPENAI_API_KEY"], "unrelated-account-key")
                self.assertEqual(alice["PWD"], str(self.root))
                private = Path(alice["XDG_DATA_HOME"])
                self.assertTrue(private.exists())
            self.assertFalse(private.exists())

    def test_missing_owner_key_never_uses_shared_login(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unrelated-key"}):
            with self.assertRaisesRegex(ValueError, "Missing owner credential"):
                with task_environment(connection(ref="KNOT_ABSENT_KEY"), self.root):
                    self.fail("Must not launch")

    def test_subprocess_receives_explicit_model_and_stdin_contract(self):
        script = self.root / "fake.py"
        script.write_text('''import os,sys,json
from pathlib import Path
request=sys.stdin.read()
args=sys.argv[1:]
assert '--standalone' in args
assert '--model' in args and '/fixture-model' in args[args.index('--model')+1]
assert os.environ['KNOT_TASK_API_KEY']=='fixture-alice-private-key'
assert 'KNOT_BOB_KEY' not in os.environ
assert 'KNOT task completion protocol' in request
print(json.dumps({'type':'step_start','sessionID':'fixture','part':{'messageID':'one'}}))
print(json.dumps({'type':'text','part':{'id':'text','messageID':'one','text':json.dumps({'status':'completed','content':'Done','data':{},'checks':[]})}}))
print(json.dumps({'type':'step_finish','part':{'reason':'stop','tokens':{'input':4,'output':8}}}))
''', encoding="utf-8")
        with patch("runtime.coding._command", return_value=[sys.executable, str(script)]):
            result = run_coding_task("opencode", "fixture-model", self.root, "Do work", 5,
                                     connection=connection())
        self.assertEqual(result["session_id"], "fixture")
        self.assertEqual(result["usage"]["output_tokens"], 8)

    def test_partial_turn_and_error_cannot_become_success(self):
        for ending in ({"type": "step_finish", "part": {"reason": "tool-calls"}},
                       {"type": "step_finish", "part": {"reason": "length"}},
                       {"type": "error", "error": {"message": "rejected"}}):
            transcript = OpenCodeTranscript(None)
            transcript.line(json.dumps({"type": "text", "part": {"text": '{"status":"completed","content":"Done","data":{}}'}}).encode())
            transcript.line(json.dumps(ending).encode())
            with self.assertRaises(RuntimeError):
                transcript.result()

    def test_reasoning_is_never_forwarded_and_last_turn_controls_completion(self):
        events = []
        transcript = OpenCodeTranscript(events.append)
        for event in [
            {"type": "step_start", "part": {"messageID": "first"}},
            {"type": "reasoning", "part": {"text": "private reasoning"}},
            {"type": "text", "part": {"messageID": "first", "text": "Working"}},
            {"type": "step_finish", "part": {"reason": "tool-calls"}},
            {"type": "step_start", "part": {"messageID": "last"}},
            {"type": "text", "part": {"id": "p", "messageID": "last", "text": '{"status":"completed",'}},
            {"type": "text", "part": {"id": "p", "messageID": "last", "text": '"content":"Done","data":{}}'}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        ]:
            transcript.line(json.dumps(event).encode())
        self.assertEqual(transcript.result()["content"], "Done")
        self.assertNotIn("private reasoning", json.dumps(events))

    def test_rejects_legacy_cli_before_execution(self):
        script = self.root / "version.py"
        script.write_text("print('1.19.5')", encoding="utf-8")
        with patch("runtime.coding._command", return_value=[sys.executable, str(script)]):
            self.assertFalse(check_backend("opencode")["available"])

    def test_accepts_official_version_banner_without_running_a_task(self):
        script = self.root / "version.py"
        script.write_text("import sys\nassert sys.argv[1:] == ['--version']\nprint('opencode v2.2.6')", encoding="utf-8")
        with patch("runtime.coding._command", return_value=[sys.executable, str(script)]):
            self.assertTrue(check_backend("opencode")["available"])

    def test_new_unfinished_message_invalidates_previous_success(self):
        transcript = OpenCodeTranscript(None)
        for event in [
            {"type": "step_start", "part": {"messageID": "done"}},
            {"type": "step_finish", "part": {"messageID": "done", "reason": "stop"}},
            {"type": "text", "part": {"messageID": "incomplete", "text": '{"status":"completed","content":"Partial","data":{}}'}},
        ]:
            transcript.line(json.dumps(event).encode())
        with self.assertRaisesRegex(RuntimeError, "terminal event"):
            transcript.result()

    def test_task_report_redacts_registered_owner_key(self):
        from runtime.security import register_secret
        register_secret("fixture-owner-sensitive-value")
        transcript = OpenCodeTranscript(None)
        for event in [
            {"type": "text", "part": {"text": '{"status":"completed","content":"fixture-owner-sensitive-value","data":{}}'}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        ]:
            transcript.line(json.dumps(event).encode())
        self.assertNotIn("fixture-owner-sensitive-value", json.dumps(transcript.result()))


class FixtureAPI:
    def __init__(self):
        self.requests = []
        self.targets = {}
        self.counts = {}
        parent = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                parent.requests.append({"auth": self.headers.get("Authorization") or self.headers.get("x-api-key"), "body": body})
                count = parent.counts.get(body["model"], 0)
                parent.counts[body["model"]] = count + 1
                response = json.dumps({"status": "completed", "content": "Fixture task completed",
                                       "data": {"model": body["model"]}, "checks": []})
                chunks = [
                    {"id": "fixture", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": response}, "finish_reason": None}]},
                    {"id": "fixture", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42}},
                ]
                if body["model"] in parent.targets and count == 0:
                    tools = {tool["function"]["name"]: tool["function"] for tool in body.get("tools", [])}
                    if "write" not in tools:
                        self.send_error(500, "OpenCode did not offer its write tool")
                        return
                    arguments = json.dumps({"path": str(parent.targets[body["model"]] / "generated.py"),
                                            "content": "print('" + body["model"] + "')\n"})
                    chunks[0]["choices"][0]["delta"] = {
                        "role": "assistant", "tool_calls": [{"index": 0, "id": "write-fixture", "type": "function",
                                                              "function": {"name": "write", "arguments": arguments}}]}
                    chunks[1]["choices"][0]["finish_reason"] = "tool_calls"
                data = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
                if self.path.endswith("/messages"):
                    events = [
                        ("message_start", {"message": {"id": "fixture", "type": "message", "role": "assistant", "model": body["model"],
                                                      "content": [], "stop_reason": None, "stop_sequence": None,
                                                      "usage": {"input_tokens": 12, "output_tokens": 0}}}),
                        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
                        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": response}}),
                        ("content_block_stop", {"index": 0}),
                        ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 30}}),
                        ("message_stop", {}),
                    ]
                    data = "".join("event: " + kind + "\ndata: " + json.dumps({"type": kind, **value}) + "\n\n" for kind, value in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@unittest.skipUnless(os.environ.get("KNOT_OPENCODE_TEST_BINARY"), "Set KNOT_OPENCODE_TEST_BINARY for real CLI against loopback fixtures")
class OpenCodeInstalledTests(OpenCodeTests):
    def test_real_cli_uses_owner_anthropic_messages_connection(self):
        api = FixtureAPI()
        self.addCleanup(api.close)
        selected = {**connection("fixture-claude", "KNOT_BOB_KEY", api.base), "provider": "anthropic"}
        with patch("runtime.coding._command", return_value=[os.environ["KNOT_OPENCODE_TEST_BINARY"]]):
            result = run_coding_task("opencode", "fixture-claude", self.root, "Return the requested completion JSON.", 60,
                                     connection=selected)
        self.assertEqual(result["data"]["model"], "fixture-claude")
        self.assertTrue(api.requests)
        self.assertEqual({r["auth"] for r in api.requests}, {"fixture-bob-private-key"})

    def test_real_cli_parallel_owners_use_distinct_models_and_keys(self):
        api = FixtureAPI()
        self.addCleanup(api.close)
        binary = os.environ["KNOT_OPENCODE_TEST_BINARY"]
        def run(name, ref):
            cwd = self.root / name
            cwd.mkdir()
            api.targets[name] = cwd
            return run_coding_task("opencode", name, cwd, "Return the requested completion JSON.", 90,
                                    connection=connection(name, ref, api.base))
        with patch("runtime.coding._command", return_value=[binary]), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, "model-a", "KNOT_ALICE_KEY")
            second = pool.submit(run, "model-b", "KNOT_BOB_KEY")
            self.assertEqual(first.result()["data"]["model"], "model-a")
            self.assertEqual(second.result()["data"]["model"], "model-b")
        routes = {(r["body"]["model"], r["auth"]) for r in api.requests}
        self.assertEqual(routes, {("model-a", "Bearer " + os.environ["KNOT_ALICE_KEY"]),
                                 ("model-b", "Bearer " + os.environ["KNOT_BOB_KEY"])})
        for model in ("model-a", "model-b"):
            self.assertEqual((self.root / model / "generated.py").read_text(), "print('" + model + "')\n")
            self.assertGreaterEqual(api.counts[model], 2, "Expected a real file-tool round trip")


if __name__ == "__main__":
    unittest.main()
