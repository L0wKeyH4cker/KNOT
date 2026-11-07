"""Behavior tests for portable orchestration; provider fixtures never spend API tokens."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from runtime.engine import Engine, WorkflowError
from runtime.providers import ProviderError, complete
from runtime.security import contains_secret, redact
from runtime.tools import ToolRunner
from runtime.validation import validate_workflow


def node(nid, kind, **config):
    return {"id": nid, "type": kind, "label": nid, "position": {"x": 0, "y": 0}, "config": config}


def task(nid, delay=10):
    return node(nid, "agent_task", agent_id="agent", owner_id="member", instructions=f"Do {nid}", acceptance="Useful result", output_format="markdown", permissions={"read": [], "write": []}, tools=[], mock_delay_ms=delay)


def edge(source, target, kind="control", port=None):
    return {"id": f"{source}_{target}_{kind}", "source": source, "target": target, "source_port": port or ("out" if kind == "control" else "data-out"), "target_port": "in" if kind == "control" else "data-in", "kind": kind}


def workflow(review=True):
    nodes = [node("start", "start"), node("parallel", "parallel"), task("left", 200), task("right", 200), task("join"), node("output", "output", mappings=[{"source_node": "join", "filename": "report.md", "format": "markdown"}])]
    edges = [edge("start", "parallel"), edge("parallel", "left"), edge("parallel", "right"), edge("left", "join"), edge("right", "join"), edge("left", "join", "data"), edge("right", "join", "data"), edge("join", "output", "data")]
    if review:
        nodes.insert(-1, node("review", "human_review", owner_id="member", instructions="Check the joined result"))
        edges.extend([edge("join", "review"), edge("join", "review", "data"), edge("review", "output")])
    else:
        edges.append(edge("join", "output"))
    return {"schema_version": "1.0", "project": {"id": "project", "name": "Test project", "goal": "Test the workflow", "deliverable": "Report", "members": [{"id": "member", "name": "Member A", "skills": ""}]},
            "agents": [{"id": "agent", "name": "Agent", "role": "Researcher", "system_prompt": "Be accurate", "provider": "openai", "model": "", "credential_ref": "TEAMBLOCKS_TEST_KEY", "tools": []}],
            "nodes": nodes, "edges": edges, "resources": [], "limits": {"max_concurrency": 2, "timeout_seconds": 5, "max_retries": 0, "max_tool_rounds": 2}, "viewport": {"x": 0, "y": 0, "zoom": 1}, "design_notes": []}


def branch_workflow(value=True, join_rule="all_selected"):
    result = workflow(review=False)
    result["nodes"] = [node("start", "start"), task("source"), node("condition", "condition", source_node="source", field="data.approved", operator="eq", value=value), task("left"), task("right"), task("join"), result["nodes"][-1]]
    result["nodes"][-2]["config"]["join_rule"] = join_rule
    result["edges"] = [edge("start", "source"), edge("source", "condition"), edge("source", "condition", "data"), edge("condition", "left", port="true"), edge("condition", "right", port="false"), edge("left", "join"), edge("right", "join"), edge("left", "join", "data"), edge("right", "join", "data"), edge("join", "output"), edge("join", "output", "data")]
    return result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-", dir=root)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_parallel_tasks_overlap_and_join_waits_for_both(self):
        result = Engine(workflow(False), self.root).run()
        self.assertEqual(result["status"], "completed")
        left, right, join = (result["nodes"][nid] for nid in ("left", "right", "join"))
        self.assertLess(max(left["started_at"], right["started_at"]), min(left["finished_at"], right["finished_at"]))
        self.assertGreaterEqual(join["started_at"], max(left["finished_at"], right["finished_at"]))
        self.assertEqual(set(result["results"]["join"]["input_nodes"]), {"left", "right"})
        self.assertTrue((self.root / "results/report.md").exists())
        self.assertNotIn("usage", result["results"]["join"])

    def test_max_concurrency_one_serializes_independent_tasks(self):
        flow = workflow(False)
        flow["limits"]["max_concurrency"] = 1
        result = Engine(flow, self.root).run()
        self.assertGreaterEqual(result["nodes"]["right"]["started_at"], result["nodes"]["left"]["finished_at"])

    def test_control_edges_do_not_grant_result_access(self):
        flow = workflow(False)
        flow["edges"] = [e for e in flow["edges"] if not (e["kind"] == "data" and e["target"] == "join")]
        result = Engine(flow, self.root).run()
        self.assertEqual(result["results"]["join"]["input_nodes"], [])

    def test_review_pauses_and_only_explicit_owner_can_resume(self):
        flow = workflow()
        initial = Engine(flow, self.root).run()
        self.assertEqual(initial["status"], "waiting_review")
        self.assertFalse((self.root / "results/report.md").exists())
        self.assertEqual(initial["nodes"]["output"]["status"], "pending")
        with self.assertRaises(PermissionError):
            Engine(flow, self.root).resume("review", "approve", "someone_else")
        finished = Engine(flow, self.root).resume("review", "approve", "member").run()
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(initial["nodes"]["join"], finished["nodes"]["join"])
        self.assertTrue((self.root / "results/report.md").exists())

    def test_rejected_review_blocks_delivery(self):
        flow = workflow()
        Engine(flow, self.root).run()
        result = Engine(flow, self.root).resume("review", "reject", "member").run()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["nodes"]["output"]["status"], "blocked")
        self.assertFalse((self.root / "results/report.md").exists())

    def test_resume_rejects_changed_workflow(self):
        flow = workflow()
        Engine(flow, self.root).run()
        flow["nodes"][2]["config"]["instructions"] = "Changed task"
        with self.assertRaisesRegex(ValueError, "Workflow changed"):
            Engine(flow, self.root).resume("review", "approve", "member")

    def test_condition_skips_unselected_branch_and_join_finishes(self):
        for comparison, skipped in ((True, "right"), (False, "left")):
            root = self.root / str(comparison)
            result = Engine(branch_workflow(comparison), root).run()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["nodes"][skipped]["status"], "skipped")
            self.assertEqual(result["nodes"]["join"]["status"], "succeeded")
            self.assertNotIn(skipped, result["results"]["join"]["input_nodes"])

    def test_all_success_join_is_skipped_when_a_branch_is_skipped(self):
        result = Engine(branch_workflow(True, "all_success"), self.root).run()
        self.assertEqual(result["nodes"]["join"]["status"], "skipped")
        self.assertEqual(result["nodes"]["output"]["status"], "skipped")
        self.assertFalse((self.root / "results/report.md").exists())

    def test_failed_dependency_blocks_join_and_output(self):
        flow = workflow(False)
        flow["nodes"][2]["config"]["mock_result"] = {"content": 99}
        result = Engine(flow, self.root).run()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["nodes"]["left"]["status"], "failed")
        self.assertEqual(result["nodes"]["join"]["status"], "blocked")
        self.assertEqual(result["nodes"]["output"]["status"], "blocked")

    def test_timeout_has_finite_retries_and_stops(self):
        flow = workflow(False)
        flow["limits"].update(timeout_seconds=1, max_retries=1)
        flow["nodes"][2]["config"]["mock_delay_ms"] = 1500
        result = Engine(flow, self.root).run()
        self.assertEqual(result["nodes"]["left"]["attempts"], 2)
        self.assertEqual(result["nodes"]["left"]["error_type"], "TimeoutError")
        self.assertEqual(result["status"], "failed")

    def test_resource_preflight_reports_missing_file(self):
        flow = workflow(False)
        flow["resources"] = [{"id": "r", "name": "Input", "path": "inputs/missing.txt", "description": "User must supply", "example": False}]
        flow["nodes"].append(node("resource", "shared_resource", resource_ids=["r"]))
        flow["edges"].append(edge("start", "resource"))
        with self.assertRaisesRegex(FileNotFoundError, "missing"):
            Engine(flow, self.root).run()

    def test_real_mode_missing_model_or_key_is_fatal(self):
        with self.assertRaises(WorkflowError):
            Engine(workflow(False), self.root, "real")
        flow = workflow(False)
        flow["agents"][0]["model"] = "configured-model"
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(WorkflowError, "not configured"):
                Engine(flow, self.root, "real")

    def test_tool_permissions_traversal_and_protected_final_paths(self):
        (self.root / "inputs").mkdir()
        (self.root / "inputs/data.csv").write_text("name,count\na,2\nb,4\n", encoding="utf-8")
        agent = {"tools": ["read_csv", "summarize_csv", "write_file"]}
        cfg = {"tools": agent["tools"], "permissions": {"read": ["inputs/data.csv"], "write": ["results"]}}
        runner = ToolRunner(self.root, agent, cfg, {"results/report.md"})
        summary = runner("summarize_csv", {"path": "inputs/data.csv"})
        self.assertEqual(summary["numeric_columns"]["count"]["mean"], 3)
        for path in ("../.env", "inputs/../.env", "C:/Windows/file", "\\\\server\\x", "inputs/data.csv:secret", "inputs/unallowed.txt"):
            with self.assertRaises((ValueError, PermissionError)):
                runner("read_csv", {"path": path})
        for path in ("results/report.md", "results/REPORT.MD", "results\\report.md"):
            with self.assertRaises(PermissionError):
                runner("write_file", {"path": path, "content": "bypass"})
        with self.assertRaises(PermissionError):
            runner("read_text", {"path": "inputs/data.csv"})
        self.assertFalse((self.root / "results/report.md").exists())

    def test_symlink_read_is_rejected(self):
        (self.root / "inputs").mkdir()
        outside = self.root / "private.txt"
        outside.write_text("private", encoding="utf-8")
        try:
            (self.root / "inputs/link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("Host does not permit creating symlinks")
        runner = ToolRunner(self.root, {"tools": ["read_text"]}, {"tools": ["read_text"], "permissions": {"read": ["inputs"], "write": []}})
        with self.assertRaises(PermissionError):
            runner("read_text", {"path": "inputs/link.txt"})

    def test_graph_cycle_and_incompatible_ports_rejected(self):
        flow = workflow(False)
        flow["edges"].append(edge("join", "left"))
        self.assertIn("cycle", {i["code"] for i in validate_workflow(flow)})
        flow = workflow(False)
        flow["edges"][0]["source_port"] = "false"
        self.assertIn("ports", {i["code"] for i in validate_workflow(flow)})

    def test_malformed_schema_always_returns_error_issues(self):
        mutations = [lambda f: f["agents"][0].update(tools=[{}]), lambda f: f["nodes"][2]["config"].update(agent_id={}), lambda f: f["nodes"][0].update(type=[]), lambda f: f["edges"][0].update(source_port={}), lambda f: f["nodes"][-1]["config"]["mappings"][0].update(source_node=[])]
        for mutation in mutations:
            flow = workflow(False)
            mutation(flow)
            self.assertTrue(any(i["severity"] == "error" for i in validate_workflow(flow)))

    def test_case_insensitive_output_collisions_rejected(self):
        flow = workflow(False)
        flow["nodes"][-1]["config"]["mappings"].append({"source_node": "join", "filename": "REPORT.MD", "format": "markdown"})
        self.assertIn("output_collision", {i["code"] for i in validate_workflow(flow)})


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TEAMBLOCKS_TEST_KEY": "fixture-secret-never-a-real-api-key"})
        self.env.start()
        self.agent = {"provider": "openai", "model": "fixture-model", "credential_ref": "TEAMBLOCKS_TEST_KEY"}

    def tearDown(self):
        self.env.stop()

    def test_openai_tool_loop_records_only_returned_usage(self):
        responses = [{"choices": [{"message": {"content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "read_text", "arguments": '{"path":"inputs/a.txt"}'}}]}}], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}, {"choices": [{"message": {"content": '{"content":"Finished","data":{"ok":true}}'}}]}]
        tool_calls = []
        with patch("runtime.providers._post", side_effect=responses) as post:
            result = complete(self.agent, "system", "task", tools=[], tool_executor=lambda name, args: tool_calls.append((name, args)) or {"text": "abc"})
        self.assertEqual(len(tool_calls), 1)
        self.assertTrue(result["data"]["data"]["ok"])
        self.assertEqual(len(result["usage"]), 1)
        payload = post.call_args_list[-1].args[2]
        self.assertEqual(payload["messages"][-1]["role"], "tool")

    def test_anthropic_messages_tool_result_protocol(self):
        self.agent["provider"] = "anthropic"
        responses = [{"content": [{"type": "tool_use", "id": "t1", "name": "read_text", "input": {"path": "inputs/a.txt"}}], "stop_reason": "tool_use", "usage": {"input_tokens": 8, "output_tokens": 2}}, {"content": [{"type": "text", "text": "Done"}], "stop_reason": "end_turn"}]
        with patch("runtime.providers._post", side_effect=responses) as post:
            result = complete(self.agent, "system", "task", tool_executor=lambda name, args: {"content": "abc"})
        self.assertEqual(result["content"], "Done")
        self.assertEqual(post.call_args.args[2]["messages"][-1]["content"][0]["type"], "tool_result")
        self.assertEqual(result["usage"][0]["input_tokens"], 8)

    def test_tool_loop_limit_never_becomes_success(self):
        response = {"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}}]}
        with patch("runtime.providers._post", return_value=response) as post:
            with self.assertRaisesRegex(ProviderError, "Maximum tool-call"):
                complete(self.agent, "s", "p", tool_executor=lambda n, a: {}, max_tool_rounds=1)
        self.assertEqual(post.call_count, 2)

    def test_missing_key_never_calls_provider(self):
        with patch.dict(os.environ, {}, clear=True), patch("runtime.providers._post") as post:
            with self.assertRaisesRegex(ProviderError, "Missing credential"):
                complete(self.agent, "s", "p")
            post.assert_not_called()

    def test_custom_credential_ref_is_redacted(self):
        secret = "custom-credential-fixture-value"
        self.agent["credential_ref"] = "CUSTOM_CREDENTIAL"
        with patch.dict(os.environ, {"CUSTOM_CREDENTIAL": secret}), patch("runtime.providers._post", return_value={"choices": [{"message": {"content": secret}}]}):
            result = complete(self.agent, "s", "p")
        self.assertEqual(result["content"], "[REDACTED]")
        self.assertTrue(contains_secret({"text": secret}))
        self.assertTrue(contains_secret({secret: "value"}))
        self.assertEqual(redact({secret: secret}), {"[REDACTED]": "[REDACTED]"})

    def test_provider_failure_never_falls_back_to_mock(self):
        with patch("runtime.providers._post", side_effect=ProviderError("HTTP 401")):
            with self.assertRaises(ProviderError):
                complete(self.agent, "s", "p")


class HTTPProviderTests(unittest.TestCase):
    """Real loopback HTTP transport against fixtures, NOT live provider validation."""

    def setUp(self):
        self.requests = []
        recorded = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                recorded.append({"path": self.path, "body": body, "has_openai_auth": bool(self.headers.get("Authorization")), "has_anthropic_auth": bool(self.headers.get("x-api-key"))})
                if self.path == "/slow/chat/completions":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    try:
                        for _ in range(30):
                            self.wfile.write(b" ")
                            self.wfile.flush()
                            time.sleep(0.08)
                    except (ConnectionError, OSError):
                        pass
                    return
                final = json.dumps({"content": "Fixture provider result", "data": {"fixture": True}})
                if self.path.endswith("/chat/completions"):
                    response = {"choices": [{"message": {"content": final}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}
                else:
                    response = {"content": [{"type": "text", "text": final}], "stop_reason": "end_turn", "usage": {"input_tokens": 8, "output_tokens": 4}}
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.env = patch.dict(os.environ, {"TEAMBLOCKS_TEST_KEY": "loopback-fixture-key-not-a-real-secret"})
        self.env.start()
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="http-provider-", dir=root)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.env.stop()
        self.temp.cleanup()

    def test_one_real_mode_workflow_mixes_both_http_protocols(self):
        flow = workflow(False)
        flow["agents"][0].update(model="fixture-openai-model", base_url=self.base + "/v1")
        anthropic = copy.deepcopy(flow["agents"][0])
        anthropic.update(id="anthropic-agent", provider="anthropic", model="fixture-anthropic-model")
        flow["agents"].append(anthropic)
        flow["nodes"][3]["config"]["agent_id"] = "anthropic-agent"
        result = Engine(flow, self.temp.name, mode="real").run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["results"]["join"]["data"], {"fixture": True})
        self.assertEqual({record["path"] for record in self.requests}, {"/v1/chat/completions", "/v1/messages"})
        self.assertEqual(len(self.requests), 3)
        prompts = [json.loads(record["body"]["messages"][-1]["content"]) for record in self.requests]
        by_task = {prompt["task"]: prompt for prompt in prompts}
        self.assertEqual(by_task["left"]["explicit_inputs"], {})
        self.assertEqual(by_task["right"]["explicit_inputs"], {})
        self.assertEqual(set(by_task["join"]["explicit_inputs"]), {"left", "right"})
        for record in self.requests:
            if record["path"].endswith("/messages"):
                self.assertTrue(record["has_anthropic_auth"])
                self.assertFalse(record["has_openai_auth"])
            else:
                self.assertTrue(record["has_openai_auth"])
                self.assertFalse(record["has_anthropic_auth"])

    def test_slow_drip_http_body_obeys_overall_deadline(self):
        agent = {"provider": "openai", "model": "fixture", "credential_ref": "TEAMBLOCKS_TEST_KEY", "base_url": self.base + "/slow"}
        started = time.monotonic()
        with self.assertRaises(ProviderError):
            complete(agent, "system", "prompt", timeout=0.3)
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == "__main__":
    unittest.main()
