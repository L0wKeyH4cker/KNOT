"""Accounting fixtures: no live models, provider billing, or invented prices."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.coding import _Transcript
from runtime.engine import Engine
from runtime.providers import ProviderError, complete
from runtime.usage import MAX_TOKENS, estimated_usd, new_entry, normalized_usage, record_event
from tests.test_local_execution import EXECUTION
from tests.test_runtime import edge, node, task, workflow


STAMP = "2026-11-08T00:00:00+00:00"


def single_task(review=False):
    flow = workflow(review)
    flow["agents"][0]["model"] = "fixture-model"
    flow["nodes"] = [node("start", "start"), task("work", 0),
                     node("output", "output", mappings=[{"source_node": "work", "filename": "report.md", "format": "markdown"}])]
    flow["edges"] = [edge("start", "work"), edge("work", "output", "data")]
    if review:
        flow["nodes"].insert(-1, node("review", "human_review", owner_id="member", instructions="Review"))
        flow["edges"].extend([edge("work", "review"), edge("work", "review", "data"), edge("review", "output")])
    else:
        flow["edges"].append(edge("work", "output"))
    return flow


def entry():
    flow = single_task()
    return new_entry({"run_id": "run"}, flow, flow["nodes"][1], 1, "real", None, STAMP)


def chat_response(usage=None, *, text='{"content":"Done","data":{}}', reason="stop"):
    return {"id": "response-1", "model": "fixture-model",
            "choices": [{"message": {"content": text}, "finish_reason": reason}], **({"usage": usage} if usage is not None else {})}


class UsageNormalizationTests(unittest.TestCase):
    def test_estimate_bounds_match_importer_after_rounding(self):
        self.assertEqual(estimated_usd("999999999999.999999"), "999999999999.999999")
        self.assertEqual(estimated_usd("0.1234565"), "0.123457")
        for amount in ("1000000000000", "1000000000000.000001", "999999999999.9999995"):
            with self.subTest(amount=amount):
                self.assertIsNone(estimated_usd(amount))

    def test_cache_tokens_are_not_added_twice_and_missing_values_stay_unknown(self):
        self.assertEqual(normalized_usage({"prompt_tokens": 100, "completion_tokens": 20,
                                          "prompt_tokens_details": {"cached_tokens": 60}}, "chat"),
                         {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 60, "cache_creation_input_tokens": None})
        self.assertEqual(normalized_usage({"input_tokens": 10, "output_tokens": 20,
                                          "cache_read_input_tokens": 60, "cache_creation_input_tokens": 30}, "claude")["input_tokens"], 100)
        self.assertIsNone(normalized_usage({"input_tokens": 10}, "claude")["input_tokens"])
        for invalid in (True, -1, MAX_TOKENS + 1, 1.5, "10"):
            self.assertIsNone(normalized_usage({"input_tokens": invalid}, "codex")["input_tokens"])

    def test_repeated_response_snapshots_replace_instead_of_add(self):
        value = entry()
        event = {"event": "response", "call_id": "1", "protocol": "chat",
                 "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 60}}}
        record_event(value, event, STAMP)
        record_event(value, event, STAMP)
        self.assertEqual(value["usage"]["input_tokens"], 100)
        self.assertEqual(value["usage"]["cached_input_tokens"], 60)
        record_event(value, {"event": "request_started", "call_id": "2"}, STAMP)
        self.assertEqual(value["usage_status"], "partial")
        record_event(value, {**event, "call_id": "2"}, STAMP)
        self.assertEqual(value["usage"]["input_tokens"], 200)
        self.assertEqual(value["usage_status"], "reported")

    def test_impossible_cache_count_is_partial_and_reportable(self):
        value = entry()
        record_event(value, {"event": "response", "call_id": "1", "protocol": "chat",
                             "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                                       "prompt_tokens_details": {"cached_tokens": 15}}}, STAMP)
        self.assertEqual(value["usage"]["input_tokens"], 10)
        self.assertIsNone(value["usage"]["cached_input_tokens"])
        self.assertEqual(value["usage_status"], "partial")

    def test_cli_error_without_usage_preserves_known_subtotal_as_partial(self):
        value = entry()
        record_event(value, {"event": "terminal", "call_id": "cli", "protocol": "codex",
                             "usage": {"input_tokens": 10, "output_tokens": 2}}, STAMP)
        record_event(value, {"event": "terminal", "call_id": "cli", "protocol": "codex"}, STAMP)
        self.assertEqual(value["usage"]["input_tokens"], 10)
        self.assertEqual(value["usage_status"], "partial")

    def test_claude_error_estimate_survives_activity_limit_and_is_never_confirmed(self):
        value = entry()
        activities = []
        transcript = _Transcript("claude", activities.append, lambda event: record_event(value, event, STAMP))
        for _ in range(5001):
            transcript.line(b'{"type":"system","subtype":"notice"}')
        terminal = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                    "total_cost_usd": 0.123456789, "usage": {"input_tokens": 12, "output_tokens": 4,
                    "cache_read_input_tokens": 8, "cache_creation_input_tokens": 0}, "result": "PRIVATE RESULT"}
        transcript.line(json.dumps(terminal).encode())
        transcript.line(json.dumps(terminal).encode())
        with self.assertRaises(RuntimeError):
            transcript.result()
        self.assertEqual(len(activities), 5000)
        self.assertEqual(value["usage"]["input_tokens"], 20)
        self.assertEqual(value["estimated_cost"], {"amount": "0.123457", "currency": "USD", "source": "Claude CLI estimate"})
        self.assertNotIn("PRIVATE RESULT", json.dumps(value))
        self.assertNotIn("confirmed_cost", value)
        empty = entry()
        record_event(empty, {"event": "terminal", "protocol": "claude", "estimated_cost_usd": 0,
                             "terminal_success": False}, STAMP)
        self.assertNotIn("estimated_cost", empty)
        self.assertEqual(empty["usage_status"], "unknown")

    def test_provider_callbacks_include_usage_before_bad_output_and_each_tool_round(self):
        flow = single_task()
        events = []
        with patch.dict(os.environ, {"KNOT_TEST_KEY": "usage-fixture-key"}), patch("runtime.providers._post", return_value=chat_response({"prompt_tokens": 12, "completion_tokens": 4}, reason="length")):
            with self.assertRaises(ProviderError):
                complete(flow["agents"][0], "system", "prompt", usage_callback=events.append)
        self.assertEqual([event["event"] for event in events], ["request_started", "response"])
        self.assertEqual(events[1]["usage"]["prompt_tokens"], 12)
        first = {"choices": [{"message": {"tool_calls": [{"id": "tool1", "type": "function",
                 "function": {"name": "read_text", "arguments": "{}"}}]}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 6}}}
        value = entry()
        with patch.dict(os.environ, {"KNOT_TEST_KEY": "usage-fixture-key"}), patch("runtime.providers._post", side_effect=[first, chat_response()]):
            complete(flow["agents"][0], "system", "prompt", tool_executor=lambda *_: "text",
                     usage_callback=lambda event: record_event(value, event, STAMP))
        self.assertEqual(len(value["calls"]), 2)
        self.assertEqual(value["usage"]["input_tokens"], 10)
        self.assertEqual(value["usage"]["cached_input_tokens"], 6)
        self.assertEqual(value["usage_status"], "partial")

    def test_responses_failed_status_still_reports_usage(self):
        flow = single_task()
        flow["agents"][0]["model"] = "gpt-6-test"
        events = []
        tool = {"name": "read_text", "description": "Read", "parameters": {"type": "object"}}
        with patch.dict(os.environ, {"KNOT_TEST_KEY": "usage-fixture-key"}), patch("runtime.providers._post", return_value={"status": "incomplete", "usage": {"input_tokens": 8, "output_tokens": 3}}):
            with self.assertRaises(ProviderError):
                complete(flow["agents"][0], "system", "prompt", tools=[tool], usage_callback=events.append)
        self.assertEqual(events[-1]["usage"]["output_tokens"], 3)


class UsageLedgerTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="usage-", dir=scratch)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"KNOT_TEST_KEY": "usage-fixture-key"})
        env.start()
        self.addCleanup(env.stop)

    def engine(self, flow=None, mode="real"):
        engine = Engine(flow or single_task(), self.root, mode, execution=EXECUTION if mode == "local" else None)
        engine.quiet = True
        return engine

    def report(self):
        return json.loads((self.root / "logs/usage-report.json").read_text(encoding="utf-8"))

    def test_failed_format_validation_keeps_tokens_and_safe_report(self):
        flow = single_task()
        flow["nodes"][1]["config"]["output_format"] = "json"
        with patch("runtime.providers._post", return_value=chat_response({"prompt_tokens": 12, "completion_tokens": 4}, text="PRIVATE RESULT NOT JSON")):
            state = self.engine(flow).run()
        value = self.report()["entries"][0]
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["usage"]["input_tokens"], 12)
        self.assertNotIn("work", state["results"])
        public = json.dumps(self.report())
        for forbidden in ("PRIVATE RESULT", "Useful result", "usage-fixture-key", "calls", "credential"):
            self.assertNotIn(forbidden, public)
        self.assertNotIn("estimated_cost", value)

    def test_automatic_retry_records_both_attempts_once(self):
        flow = single_task()
        flow["limits"]["max_retries"] = 1
        responses = [chat_response({"prompt_tokens": 10, "completion_tokens": 2}, reason="length"),
                     chat_response({"prompt_tokens": 20, "completion_tokens": 3})]
        with patch("runtime.providers._post", side_effect=responses):
            state = self.engine(flow).run()
        entries = self.report()["entries"]
        self.assertEqual(state["status"], "completed")
        self.assertEqual([value["status"] for value in entries], ["failed", "succeeded"])
        self.assertEqual([value["attempt"] for value in entries], [1, 2])
        self.assertEqual(sum(value["usage"]["input_tokens"] for value in entries), 30)
        self.assertEqual(len({value["id"] for value in entries}), 2)

    def test_unknown_provider_usage_and_mock_are_not_zero_cost(self):
        with patch("runtime.providers._post", return_value=chat_response()):
            self.engine().run()
        value = self.report()["entries"][0]
        self.assertEqual(value["usage_status"], "unknown")
        self.assertTrue(all(item is None for item in value["usage"].values()))
        mock_root = self.root / "mock"
        mock = Engine(single_task(), mock_root, "mock")
        state = mock.run()
        value = next(iter(state["usage_ledger"].values()))
        self.assertEqual(value["usage_status"], "simulated")
        self.assertNotIn("estimated_cost", value)

    def test_local_retry_and_review_resume_do_not_duplicate_usage(self):
        flow = single_task(review=True)

        def worker(_backend, _model, _cwd, _prompt, _timeout, **kwargs):
            kwargs["usage_callback"]({"event": "terminal", "protocol": "codex", "call_id": "cli",
                                      "usage": {"input_tokens": 9, "output_tokens": 2, "cached_input_tokens": 4}})
            return {"content": "done", "data": {}, "checks": []}

        def failed(*args, **kwargs):
            worker(*args, **kwargs)
            raise RuntimeError("Task failed after consuming tokens")

        with patch("runtime.coding.run_coding_task", side_effect=failed):
            self.engine(flow, "local").run()
        with patch("runtime.coding.run_coding_task", side_effect=worker):
            state = self.engine(flow, "local").retry_failed().run()
        self.assertEqual(state["status"], "waiting_review")
        before = deepcopy(state["usage_ledger"])
        with patch("runtime.coding.run_coding_task") as called:
            state = self.engine(flow, "local").resume("review", "approve", "member").run()
        called.assert_not_called()
        self.assertEqual(state["usage_ledger"], before)
        self.assertEqual(sum(value["usage"]["input_tokens"] for value in before.values()), 18)

    def test_old_saved_run_is_legacy_instead_of_inferred_from_results(self):
        flow = single_task(review=True)
        engine = self.engine(flow, "mock")
        state = engine.run()
        state.pop("usage_ledger")
        state["results"]["work"]["usage"] = {"input_tokens": 12345}
        (self.root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
        final = self.engine(flow, "mock").resume("review", "approve", "member").run()
        value = next(iter(final["usage_ledger"].values()))
        self.assertEqual(value["usage_status"], "legacy")
        self.assertIsNone(value["usage"]["input_tokens"])

    def test_report_write_failure_warns_but_keeps_authoritative_ledger(self):
        engine = self.engine(mode="mock")
        original = Path.write_text

        def write(path, *args, **kwargs):
            if path.name == "usage-report.json.tmp":
                raise PermissionError("Simulated report file lock")
            return original(path, *args, **kwargs)

        with patch.object(Path, "write_text", write):
            state = engine.run()
        self.assertEqual(state["status"], "completed")
        saved = json.loads((self.root / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["usage_ledger"], state["usage_ledger"])
        self.assertEqual(len([item for item in state["warnings"] if item["code"] == "usage_report"]), 1)
        engine._save()
        self.assertEqual(len(self.report()["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
