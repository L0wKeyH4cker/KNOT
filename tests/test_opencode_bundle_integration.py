"""Opt-in exported runner acceptance with the installed OpenCode and local fake APIs.

Set KNOT_OPENCODE_TEST_BINARY to an OpenCode 2.2.6+ executable. The CLI performs
real file-tool operations; all model replies and credentials are fictional.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

from backend.bundle import build_bundle
from tests.test_owner_connections import EXECUTION, REF_A, REF_B, owner_workflow


class BundleFixtureAPI:
    """Drive the real coding CLI through writes, source reads and final reports."""
    def __init__(self, runner: Path, flow: dict):
        self.workspaces = {node["id"]: runner / ".knot" / "tasks" / f"task-{index:03d}-{node['id']}" / "work"
                           for index, node in enumerate(flow["nodes"], 1) if node["type"] == "agent_task"}
        self.requests = []
        self.errors = []
        self.counts = {}
        self.join_inputs = None
        self.lock = threading.Lock()
        self.parallel = threading.Barrier(2)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                try:
                    task, delta, finish = parent.reply(body, self.headers.get("Authorization"))
                except Exception as error:
                    with parent.lock:
                        parent.errors.append(f"{type(error).__name__}: {error}")
                    task = "failed-fixture"
                    delta = {"role": "assistant", "content": json.dumps({
                        "status": "blocked", "content": "Local integration fixture failed", "data": {}, "checks": []})}
                    finish = "stop"
                chunks = [
                    {"id": "fixture-" + task, "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                     "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"id": "fixture-" + task, "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                     "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}},
                ]
                data = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
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
        self.thread.join(timeout=3)

    def reply(self, body, authorization):
        assignment = None
        for message in body.get("messages", []):
            content = message.get("content", "")
            if isinstance(content, list):
                content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
            if isinstance(content, str) and "Assigned work:\n" in content:
                assignment = json.JSONDecoder().raw_decode(content.split("Assigned work:\n", 1)[1])[0]
                break
        if assignment is None:
            raise AssertionError("The exported task assignment was not sent to the model")
        task = assignment["task"]["id"]
        if task not in self.workspaces:
            raise AssertionError("Unexpected task requested by exported runner")
        with self.lock:
            turn = self.counts.get(task, 0)
            self.counts[task] = turn + 1
            self.requests.append({"task": task, "model": body["model"], "authorization": authorization, "body": body})
        work = self.workspaces[task]
        tools = {tool["function"]["name"] for tool in body.get("tools", [])}
        tool_results = [message for message in body["messages"] if message.get("role") == "tool"]

        def call(name, arguments):
            if name not in tools:
                raise AssertionError(f"OpenCode did not offer the {name} tool")
            return task, {"role": "assistant", "tool_calls": [{
                "index": 0, "id": f"{task}-tool-{turn}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}, "tool_calls"

        if task in ("left", "right"):
            expected = f"value = {2 if task == 'left' else 3}\n"
            if turn == 0:
                self.parallel.wait(timeout=25)
                return call("write", {"path": str(work / (task + ".py")), "content": expected})
            if (work / (task + ".py")).read_text(encoding="utf-8") != expected:
                raise AssertionError("OpenCode file tool did not produce the assigned source")
        else:
            if turn == 0:
                # These files must already be materialized by KNOT's data edges.
                if (work / "left.py").read_text(encoding="utf-8") != "value = 2\n":
                    raise AssertionError("Left source was not handed to join")
                if (work / "right.py").read_text(encoding="utf-8") != "value = 3\n":
                    raise AssertionError("Right source was not handed to join")
                self.join_inputs = json.loads((work / ".knot-context" / "input-data.json").read_text(encoding="utf-8"))
                return call("read", {"path": str(work / "left.py")})
            if turn == 1:
                if not tool_results or "value = 2" not in json.dumps(tool_results[-1].get("content")):
                    raise AssertionError("Join's real read tool did not return the left source")
                return call("read", {"path": str(work / "right.py")})
            if turn == 2:
                if not tool_results or "value = 3" not in json.dumps(tool_results[-1].get("content")):
                    raise AssertionError("Join's real read tool did not return the right source")
                return call("write", {"path": str(work / "joined.py"),
                                      "content": "from left import value as a\nfrom right import value as b\nprint(a + b)\n"})
            if not (work / "joined.py").is_file():
                raise AssertionError("Join did not write its integrated source file")
        if not tool_results:
            raise AssertionError("A model result was returned without a real tool round trip")
        return task, {"role": "assistant", "content": json.dumps({
            "status": "completed", "content": "Completed fixture task " + task,
            "data": {"task": task, "model": body["model"]}, "checks": [],
        })}, "stop"


@unittest.skipUnless(os.environ.get("KNOT_OPENCODE_TEST_BINARY"), "Set KNOT_OPENCODE_TEST_BINARY for real exported OpenCode acceptance")
class OpenCodeBundleIntegrationTests(unittest.TestCase):
    def test_exported_runner_routes_parallel_owners_and_delivers_joined_code(self):
        binary = Path(os.environ["KNOT_OPENCODE_TEST_BINARY"]).resolve(strict=True)
        self.assertTrue(binary.is_file())
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="opencode-bundle-", dir=scratch) as temporary:
            root = Path(temporary)
            runner = root / "runner"
            runner.mkdir()
            flow = owner_workflow(False)
            api = BundleFixtureAPI(runner, flow)
            self.addCleanup(api.close)
            for member in flow["project"]["members"]:
                member["connection"]["base_url"] = api.base
            execution = {**EXECUTION, "task_timeout_seconds": 90}
            archive_bytes = build_bundle(flow, execution)
            keys = {REF_A: "fixture-bundle-alice-14398", REF_B: "fixture-bundle-bob-65372"}
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                self.assertIn("runtime/opencode.py", archive.namelist())
                self.assertIn("runtime/owner_connections.py", archive.namelist())
                for name in archive.namelist():
                    for value in keys.values():
                        self.assertNotIn(value.encode(), archive.read(name))
                archive.extractall(runner)
            (runner / ".env").write_text("\n".join(f"{ref}={value}" for ref, value in keys.items()) + "\n", encoding="utf-8")
            environment = dict(os.environ)
            for ref in keys:
                environment.pop(ref, None)
            environment.update({"PATH": str(binary.parent) + os.pathsep + environment.get("PATH", ""),
                                "KNOT_RUNS_DIR": str(root / "registry"), "PYTHONUTF8": "1"})
            completed = subprocess.run([sys.executable, "-X", "utf8", "knot.py", "run", "--plain"],
                                       cwd=runner, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=180)
            diagnostics = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 0, diagnostics + "\n" + repr(api.errors))
            self.assertEqual(api.errors, [])
            state = json.loads((runner / "logs/run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["execution"]["backend"], "opencode")
            expected_routes = {("left", "fixture-alice", "Bearer " + keys[REF_A]),
                               ("right", "fixture-bob", "Bearer " + keys[REF_B]),
                               ("join", "fixture-alice", "Bearer " + keys[REF_A])}
            self.assertEqual({(r["task"], r["model"], r["authorization"]) for r in api.requests}, expected_routes)
            self.assertGreaterEqual(api.counts["left"], 2)
            self.assertGreaterEqual(api.counts["right"], 2)
            self.assertGreaterEqual(api.counts["join"], 4)
            left, right, join = (state["nodes"][task] for task in ("left", "right", "join"))
            self.assertLess(max(left["started_at"], right["started_at"]), min(left["finished_at"], right["finished_at"]))
            self.assertGreaterEqual(join["started_at"], max(left["finished_at"], right["finished_at"]))
            self.assertEqual(set(api.join_inputs), {"left", "right"})
            self.assertEqual(api.join_inputs["right"]["data"]["model"], "fixture-bob")
            self.assertEqual(set(state["results"]["join"]["input_nodes"]), {"left", "right"})
            project = runner / "results/project"
            self.assertEqual((project / "left.py").read_text(encoding="utf-8"), "value = 2\n")
            self.assertEqual((project / "right.py").read_text(encoding="utf-8"), "value = 3\n")
            checked = subprocess.run([sys.executable, "joined.py"], cwd=project, capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(checked.stdout.strip(), "5")
            for path in (runner / "logs").iterdir():
                if path.is_file():
                    diagnostics += path.read_text(encoding="utf-8")
            for value in keys.values():
                self.assertNotIn(value, diagnostics)


if __name__ == "__main__":
    unittest.main()
