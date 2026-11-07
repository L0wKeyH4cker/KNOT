"""Multi-backend routing over real loopback HTTP, never live provider APIs.

Three independent fixture servers reject the wrong model, path or credential.
Only the responses are fixtures: Engine, HTTP adapters, ZIP export and the
exported subprocess execute their normal real-mode code paths.
"""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import zipfile

from backend.bundle import build_bundle
from runtime.engine import Engine, WorkflowError


class FixtureBackend:
    def __init__(self, name, provider, model, credential):
        self.name, self.provider, self.model = name, provider, model
        self.requests = []
        self.reject_auth = False
        self.barrier = None
        backend = self
        expected_path = f"/{name}/v1/" + ("messages" if provider == "anthropic" else "chat/completions")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                bearer = self.headers.get("Authorization")
                api_key = self.headers.get("x-api-key")
                auth_ok = (api_key == credential and bearer is None) if provider == "anthropic" else (bearer == "Bearer " + credential and api_key is None)
                # Do not retain credential/header values, even in fixture records.
                record = {"path": self.path, "model": body.get("model"), "auth_ok": auth_ok,
                          "body": body, "started": time.monotonic()}
                backend.requests.append(record)
                status = 200
                if not auth_ok or backend.reject_auth:
                    status = 401
                    payload = {"error": {"type": "authentication_error", "code": "invalid_api_key", "message": "Fixture rejection"}}
                elif self.path != expected_path or body.get("model") != model:
                    status = 400
                    payload = {"error": {"type": "invalid_request_error", "message": "Wrong fixture endpoint or model"}}
                else:
                    if backend.barrier is not None:
                        backend.barrier.wait(timeout=3)
                    result = json.dumps({"content": f"Fixture result from {name}.",
                                         "data": {"backend": name, "model": model}})
                    if provider == "anthropic":
                        payload = {"content": [{"type": "text", "text": result}], "stop_reason": "end_turn",
                                   "usage": {"input_tokens": 11, "output_tokens": 5}}
                    else:
                        payload = {"choices": [{"message": {"content": result}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 13, "completion_tokens": 6}}
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                record["finished"] = time.monotonic()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/{name}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def edge(source, target, kind="control"):
    return {"id": f"{source}-{target}-{kind}", "source": source, "target": target,
            "source_port": "out" if kind == "control" else "data-out",
            "target_port": "in" if kind == "control" else "data-in", "kind": kind}


def node(nid, kind, **config):
    return {"id": nid, "type": kind, "label": nid, "position": {"x": 0, "y": 0}, "config": config}


class MultiProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="multi-provider-", dir=scratch)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(scratch.resolve()))
        self.addCleanup(self.temp.cleanup)
        self.credentials = {
            "KNOT_ROUTE_RESEARCH_KEY": "fixture-routing-research-not-a-real-key",
            "KNOT_ROUTE_CALCULATION_KEY": "fixture-routing-calculation-not-a-real-key",
            "KNOT_ROUTE_SYNTHESIS_KEY": "fixture-routing-synthesis-not-a-real-key",
        }
        environment = patch.dict(os.environ, self.credentials)
        environment.start()
        self.addCleanup(environment.stop)
        self.backends = {}
        agents, tasks = [], []
        roles = [
            ("research", "openai", "fixture-research-model", "KNOT_ROUTE_RESEARCH_KEY", "Find evidence for the report."),
            ("calculation", "anthropic", "fixture-calculation-model", "KNOT_ROUTE_CALCULATION_KEY", "Calculate and explain the supplied numbers."),
            ("synthesis", "openai", "fixture-gateway-model", "KNOT_ROUTE_SYNTHESIS_KEY", "Combine only the explicitly connected results."),
        ]
        for name, provider, model, ref, instructions in roles:
            backend = FixtureBackend(name, provider, model, self.credentials[ref])
            self.backends[name] = backend
            self.addCleanup(backend.close)
            agents.append({"id": name + "-agent", "name": name, "role": name,
                           "system_prompt": f"You perform {name} only.", "provider": provider,
                           "model": model, "credential_ref": ref, "base_url": backend.base_url, "tools": []})
            tasks.append(node(name, "agent_task", agent_id=name + "-agent", owner_id=name + "-owner",
                              instructions=instructions, acceptance="Preserve source limitations.", output_format="markdown",
                              permissions={"read": [], "write": []}, tools=[], join_rule="all_selected"))
        self.flow = {
            "schema_version": "1.0",
            "project": {"id": "multi-provider", "name": "Three independent backend test", "goal": "Verify model division of work.",
                        "deliverable": "A report", "members": [{"id": name + "-owner", "name": name, "skills": ""} for name, *_ in roles]},
            "agents": agents,
            "nodes": [node("start", "start"), node("parallel", "parallel"), *tasks,
                      node("output", "output", mappings=[{"source_node": "synthesis", "filename": "report.md", "format": "markdown"}])],
            "edges": [edge("start", "parallel"), edge("parallel", "research"), edge("parallel", "calculation"),
                      edge("research", "synthesis"), edge("calculation", "synthesis"),
                      edge("research", "synthesis", "data"), edge("calculation", "synthesis", "data"),
                      edge("synthesis", "output"), edge("synthesis", "output", "data")],
            "resources": [], "limits": {"max_concurrency": 2, "timeout_seconds": 8, "max_retries": 0, "max_tool_rounds": 2},
            "viewport": {"x": 0, "y": 0, "zoom": 1}, "design_notes": ["Independent fixture endpoints, credentials and task models."],
        }

    def prompt(self, name):
        return json.loads(self.backends[name].requests[0]["body"]["messages"][-1]["content"])

    def assert_no_credentials_in_run(self, state, root=None):
        directory = Path(root or self.root)
        rendered = json.dumps(state) + "\n" + "\n".join(path.read_text(encoding="utf-8") for path in (directory / "logs").glob("*.json*"))
        for credential in self.credentials.values():
            self.assertNotIn(credential, rendered)

    def assert_routing(self):
        self.assertEqual(len({backend.server.server_port for backend in self.backends.values()}), 3)
        for agent in self.flow["agents"]:
            name = agent["name"]
            backend = self.backends[name]
            self.assertEqual(len(backend.requests), 1)
            request = backend.requests[0]
            self.assertTrue(request["auth_ok"], name)
            self.assertEqual(request["model"], agent["model"])
            endpoint = "messages" if agent["provider"] == "anthropic" else "chat/completions"
            self.assertEqual(request["path"], f"/{name}/v1/{endpoint}")
            self.assertEqual(self.prompt(name)["task"], name)
            task = next(task for task in self.flow["nodes"] if task["id"] == name)
            self.assertEqual(self.prompt(name)["instructions"], task["config"]["instructions"])
            body = request["body"]
            system = body["system"] if agent["provider"] == "anthropic" else body["messages"][0]["content"]
            self.assertEqual(system, agent["system_prompt"])

    def test_three_distinct_backends_models_and_keys_run_parallel_work_then_join(self):
        barrier = threading.Barrier(2)
        self.backends["research"].barrier = self.backends["calculation"].barrier = barrier
        state = Engine(self.flow, self.root, mode="real").run()
        self.assertEqual(state["status"], "completed")
        self.assert_routing()
        self.assertEqual(self.prompt("research")["explicit_inputs"], {})
        self.assertEqual(self.prompt("calculation")["explicit_inputs"], {})
        joined = self.prompt("synthesis")["explicit_inputs"]
        self.assertEqual(set(joined), {"research", "calculation"})
        for name in ("research", "calculation"):
            self.assertEqual(joined[name]["data"]["backend"], name)
            self.assertEqual(joined[name]["mode"], "real")
        left, right, join = (state["nodes"][name] for name in ("research", "calculation", "synthesis"))
        self.assertLess(max(left["started_at"], right["started_at"]), min(left["finished_at"], right["finished_at"]))
        self.assertGreaterEqual(join["started_at"], max(left["finished_at"], right["finished_at"]))
        self.assertEqual((self.root / "results/report.md").read_text(encoding="utf-8"), "Fixture result from synthesis.\n")
        self.assert_no_credentials_in_run(state)

    def test_control_dependency_does_not_share_another_backend_result(self):
        self.flow["edges"] = [link for link in self.flow["edges"] if not (link["source"] == "calculation" and link["kind"] == "data")]
        state = Engine(self.flow, self.root, mode="real").run()
        self.assertEqual(state["status"], "completed")
        self.assert_routing()
        self.assertEqual(set(self.prompt("synthesis")["explicit_inputs"]), {"research"})
        self.assertGreaterEqual(state["nodes"]["synthesis"]["started_at"], state["nodes"]["calculation"]["finished_at"])

    def test_provider_auth_failure_blocks_join_and_never_falls_back(self):
        self.backends["calculation"].reject_auth = True
        state = Engine(self.flow, self.root, mode="real").run()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["nodes"]["research"]["status"], "succeeded")
        self.assertEqual(state["nodes"]["calculation"]["status"], "failed")
        self.assertEqual(state["nodes"]["calculation"]["error_type"], "ProviderError")
        self.assertEqual(state["nodes"]["calculation"]["attempts"], 1)
        self.assertEqual(state["nodes"]["synthesis"]["status"], "blocked")
        self.assertEqual(state["nodes"]["output"]["status"], "blocked")
        self.assertNotIn("calculation", state["results"])
        self.assertEqual(self.backends["synthesis"].requests, [])
        self.assertFalse((self.root / "results/report.md").exists())
        self.assert_no_credentials_in_run(state)

    def test_wrong_credential_reference_is_not_replaced_by_another_key(self):
        self.flow["agents"][0]["credential_ref"] = "KNOT_ROUTE_CALCULATION_KEY"
        state = Engine(self.flow, self.root, mode="real").run()
        self.assertEqual(state["status"], "failed")
        self.assertFalse(self.backends["research"].requests[0]["auth_ok"])
        self.assertTrue(self.backends["calculation"].requests[0]["auth_ok"])
        self.assertEqual(state["nodes"]["research"]["status"], "failed")
        self.assertEqual(state["nodes"]["calculation"]["status"], "succeeded")
        self.assertEqual(self.backends["synthesis"].requests, [])
        self.assert_no_credentials_in_run(state)

    def test_missing_one_backend_key_stops_preflight_before_any_http(self):
        with patch.dict(os.environ, self.credentials):
            os.environ.pop("KNOT_ROUTE_CALCULATION_KEY")
            with self.assertRaises(WorkflowError):
                Engine(self.flow, self.root, mode="real")
        self.assertTrue(all(not backend.requests for backend in self.backends.values()))

    def test_export_preserves_independent_routing_and_runs_portably(self):
        original = copy.deepcopy(self.flow)
        bundle = build_bundle(self.flow)
        target = self.root / "exported"
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertEqual(json.loads(archive.read("workflow.json")), original)
            examples = archive.read(".env.example").decode("utf-8")
            self.assertEqual({line for line in examples.splitlines() if line and not line.startswith("#")}, {ref + "=" for ref in self.credentials})
            for name in archive.namelist():
                content = archive.read(name)
                for credential in self.credentials.values():
                    self.assertNotIn(credential.encode(), content, name)
            # This is our own generated, already validated archive.
            archive.extractall(target)
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        finished = subprocess.run([sys.executable, "-X", "utf8", "run.py", "--mode", "real"], cwd=target,
                                  env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        state = json.loads((target / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "completed")
        self.assert_routing()
        self.assertEqual(set(self.prompt("synthesis")["explicit_inputs"]), {"research", "calculation"})
        self.assert_no_credentials_in_run(state, target)
        self.assertEqual(self.flow, original)


if __name__ == "__main__":
    unittest.main()
