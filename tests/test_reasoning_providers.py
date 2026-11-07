"""Reasoning/tool protocol fixtures; no credentials or network model calls."""
import copy
import json
import os
import unittest
from unittest.mock import Mock, patch

from runtime.providers import ProviderError, complete


TOOLS = [{"name": "read_text", "description": "Read permitted text.",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"], "additionalProperties": False}}]


def call(call_id="call-1", name="read_text", arguments='{"path":"inputs/a.txt"}'):
    return {"type": "function_call", "id": "fc-" + call_id, "call_id": call_id,
            "name": name, "arguments": arguments, "status": "completed"}


def message(text="Done"):
    return {"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def response(*items, status="completed"):
    return {"status": status, "output": list(items), "usage": {"input_tokens": 7, "output_tokens": 3}}


class ReasoningProviderTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"KNOT_REASONING_TEST_KEY": "fixture-reasoning-not-a-live-key"})
        environment.start()
        self.addCleanup(environment.stop)
        self.agent = {"provider": "openai", "model": "gpt-6-luna", "credential_ref": "KNOT_REASONING_TEST_KEY"}

    def complete(self, **kwargs):
        return complete(self.agent, "Role instructions", "Task input", **kwargs)

    def test_stateless_responses_preserves_all_reasoning_items_and_call_outputs(self):
        reasoning = {"type": "reasoning", "id": "rs-1", "encrypted_content": "opaque-reasoning-state",
                     "summary": [{"type": "summary_text", "text": "private-reasoning-fixture"}]}
        first = response(reasoning, message("Tool preface"), call())
        second = response(message('{"content":"Finished","data":{"ok":true}}'))
        requests = []
        def post(url, headers, payload, timeout):
            requests.append(copy.deepcopy(payload))
            self.assertEqual(url, "https://api.openai.com/v1/responses")
            return [first, second][len(requests) - 1]
        execute = Mock(return_value={"text": "file content"})
        with patch("runtime.providers._post", side_effect=post):
            result = self.complete(tools=TOOLS, tool_executor=execute)
        self.assertEqual(len(requests), 2)
        initial, followup = requests
        self.assertFalse(initial["store"])
        self.assertEqual(initial["include"], ["reasoning.encrypted_content"])
        self.assertEqual(initial["instructions"], "Role instructions")
        self.assertEqual(initial["input"], [{"role": "user", "content": "Task input"}])
        self.assertEqual(initial["tools"][0]["type"], "function")
        self.assertEqual(initial["tools"][0]["name"], "read_text")
        self.assertNotIn("function", initial["tools"][0])
        self.assertEqual(followup["input"][1:4], first["output"])
        self.assertEqual(followup["input"][-1], {"type": "function_call_output", "call_id": "call-1", "output": '{"text": "file content"}'})
        self.assertNotIn("previous_response_id", followup)
        execute.assert_called_once_with("read_text", {"path": "inputs/a.txt"})
        self.assertTrue(result["data"]["data"]["ok"])
        self.assertEqual(len(result["usage"]), 2)
        self.assertNotIn("private-reasoning-fixture", json.dumps(result))
        self.assertNotIn("opaque-reasoning-state", json.dumps(result))

    def test_route_is_limited_to_official_gpt6_with_tools(self):
        cases = [
            ("gpt-6-luna", None, TOOLS, "responses"),
            ("gpt-6-sol", None, TOOLS, "responses"),
            ("gpt-6.1-sol", None, TOOLS, "responses"),
            ("gpt-6-astra", "https://api.openai.com/v1", TOOLS, "responses"),
            ("gpt-6-astra", None, [], "chat/completions"),
            ("gpt-4.1", None, TOOLS, "chat/completions"),
            ("gpt-6-luna", "https://compatible.example/v1", TOOLS, "chat/completions"),
            ("gpt-6-luna", "https://api.openai.com.example/v1", TOOLS, "chat/completions"),
            ("deepseek-v4-pro", "https://api.deepseek.com", TOOLS, "chat/completions"),
        ]
        for model, base, tools, endpoint in cases:
            with self.subTest(model=model, base=base, tools=bool(tools)):
                self.agent.update(model=model, base_url=base)
                value = response(message()) if endpoint == "responses" else {"choices": [{"message": {"content": "Done"}}]}
                with patch("runtime.providers._post", return_value=value) as post:
                    self.complete(tools=tools, tool_executor=Mock())
                self.assertTrue(post.call_args.args[0].endswith("/" + endpoint))

    def test_invalid_and_refused_responses_never_invoke_tools(self):
        invalid = [
            response(call(), status="incomplete"),
            response(call(), status="failed"),
            response(call(), {"type": "web_search_call"}),
            response(call(), {"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "private refusal"}]}),
            response(call(), message(None)),
            response(call(), call()),
            response(call(arguments="not-json")),
            response(call(arguments="[]")),
            response({**call(), "status": "incomplete"}),
            response({**call(), "call_id": ""}),
            response({"type": "reasoning", "summary": []}),
        ]
        for value in invalid:
            with self.subTest(value=value):
                execute = Mock()
                with patch("runtime.providers._post", return_value=value), self.assertRaises(ProviderError):
                    self.complete(tools=TOOLS, tool_executor=execute)
                execute.assert_not_called()

    def test_ungranted_tool_or_missing_executor_is_rejected(self):
        execute = Mock()
        with patch("runtime.providers._post", return_value=response(call(name="shell"))), self.assertRaises(PermissionError):
            self.complete(tools=TOOLS, tool_executor=execute)
        execute.assert_not_called()
        with patch("runtime.providers._post", return_value=response(call())), self.assertRaises(PermissionError):
            self.complete(tools=TOOLS)

    def test_repeated_call_id_across_rounds_does_not_repeat_side_effect(self):
        execute = Mock(return_value={"text": "a"})
        with patch("runtime.providers._post", side_effect=[response(call()), response(call())]), self.assertRaisesRegex(ProviderError, "duplicate"):
            self.complete(tools=TOOLS, tool_executor=execute)
        self.assertEqual(execute.call_count, 1)

    def test_tool_round_and_batch_limits_are_enforced_before_execution(self):
        execute = Mock()
        with patch("runtime.providers._post", return_value=response(call())), self.assertRaisesRegex(ProviderError, "rounds"):
            self.complete(tools=TOOLS, tool_executor=execute, max_tool_rounds=0)
        execute.assert_not_called()
        with patch("runtime.providers._post", return_value=response(*(call(str(i)) for i in range(17)))), self.assertRaisesRegex(ProviderError, "Too many"):
            self.complete(tools=TOOLS, tool_executor=execute)
        execute.assert_not_called()

    def test_tool_failure_and_deadline_stop_further_requests(self):
        with patch("runtime.providers._post", return_value=response(call())) as post, self.assertRaises(PermissionError):
            self.complete(tools=TOOLS, tool_executor=Mock(side_effect=PermissionError("denied fixture path")))
        self.assertEqual(post.call_count, 1)
        with patch("runtime.providers.time.monotonic", side_effect=[10, 10, 12]), patch("runtime.providers._post", return_value=response(call())) as post, self.assertRaises(TimeoutError):
            self.complete(tools=TOOLS, tool_executor=Mock(), timeout=1)
        self.assertEqual(post.call_count, 1)
        with patch("runtime.providers._post") as post, self.assertRaises(TimeoutError):
            self.complete(tools=TOOLS, tool_executor=Mock(), timeout=0)
        post.assert_not_called()

    def test_deepseek_chat_tool_loop_returns_reasoning_only_to_its_provider(self):
        self.agent.update(model="deepseek-v4-pro", base_url="https://api.deepseek.com")
        internal = "private-thinking-fixture"
        first = {"choices": [{"message": {"content": None, "reasoning_content": internal, "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "read_text", "arguments": '{"path":"inputs/a.txt"}'}}]}}]}
        last = {"choices": [{"message": {"content": "Final visible answer", "reasoning_content": "final-private-thinking"}}]}
        requests = []
        def post(url, headers, payload, timeout):
            self.assertEqual(url, "https://api.deepseek.com/chat/completions")
            requests.append(copy.deepcopy(payload))
            return [first, last][len(requests) - 1]
        with patch("runtime.providers._post", side_effect=post):
            result = self.complete(tools=TOOLS, tool_executor=lambda name, args: {"text": "data"})
        assistant = requests[1]["messages"][-2]
        self.assertEqual(assistant["reasoning_content"], internal)
        self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
        self.assertEqual(result["content"], "Final visible answer")
        self.assertNotIn(internal, json.dumps(result))
        self.assertNotIn("final-private-thinking", json.dumps(result))

    def test_nonstring_chat_reasoning_is_not_forwarded(self):
        self.agent.update(model="deepseek-v4-flash", base_url="https://api.deepseek.com")
        first = {"choices": [{"message": {"content": None, "reasoning_content": {"bad": True}, "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "read_text", "arguments": "{}"}}]}}]}
        last = {"choices": [{"message": {"content": "Done"}}]}
        with patch("runtime.providers._post", side_effect=[first, last]) as post:
            self.complete(tools=TOOLS, tool_executor=lambda name, args: {})
        self.assertNotIn("reasoning_content", post.call_args.args[2]["messages"][-2])


if __name__ == "__main__":
    unittest.main()
