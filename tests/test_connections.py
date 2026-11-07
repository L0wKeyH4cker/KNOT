"""Credential persistence and DeepSeek-compatible requests without live API calls."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from backend.connections import DEEPSEEK_CONNECTION, credential_status, save_credential, test_connection
from backend.bundle import build_bundle
from backend.planner import PlanningError
from backend.template import load_template
from runtime.providers import ProviderError, complete
import io
import zipfile


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="knot-connections-", dir=temporary_root)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.secret = "dummy-deepseek-connection-fixture"

    def test_save_preserves_other_settings_and_updates_current_process(self):
        path = self.root / ".env.local"
        path.write_text("# Keep this comment\nOTHER_API_KEY=other-fixture\n", encoding="utf-8")
        result = save_credential(self.root, "DEEPSEEK_API_KEY", self.secret)
        self.assertIn("# Keep this comment", path.read_text())
        self.assertIn("OTHER_API_KEY=other-fixture", path.read_text())
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], self.secret)
        self.assertTrue(result["DEEPSEEK_API_KEY"])
        self.assertNotIn(self.secret, json.dumps(result))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_replacing_key_leaves_one_entry_and_no_temporary_file(self):
        save_credential(self.root, "DEEPSEEK_API_KEY", self.secret)
        save_credential(self.root, "DEEPSEEK_API_KEY", "replacement-dummy-credential")
        self.assertEqual((self.root / ".env.local").read_text().count("DEEPSEEK_API_KEY="), 1)
        self.assertNotIn(self.secret, (self.root / ".env.local").read_text())
        self.assertEqual(list(self.root.glob(".env.local.*")), [])

    def test_rejects_environment_override_and_multiline_credentials(self):
        for ref, key in (("PATH", self.secret), ("DEEPSEEK_API_KEY", "value\nPATH=bad"), ("DEEPSEEK_API_KEY", "")):
            with self.subTest(ref=ref), self.assertRaises(PlanningError):
                save_credential(self.root, ref, key)
        self.assertFalse((self.root / ".env.local").exists())

    def test_refuses_to_overwrite_symlink_target(self):
        target = self.root / "untouched.txt"
        target.write_text("original")
        try:
            (self.root / ".env.local").symlink_to(target)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows has not granted symbolic-link creation permission")
            raise
        with self.assertRaises(PlanningError):
            save_credential(self.root, "DEEPSEEK_API_KEY", self.secret)
        self.assertEqual(target.read_text(), "original")

    def test_deepseek_uses_compatible_endpoint_and_bounded_generic_prompt(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        with patch("backend.connections._post", return_value={"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}) as post:
            result = test_connection(DEEPSEEK_CONNECTION)
        url, headers, payload, timeout = post.call_args.args
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer " + self.secret)
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["max_tokens"], 16)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Reply with OK."}])
        self.assertEqual(timeout, 30)
        self.assertTrue(result["ok"])
        self.assertNotIn(self.secret, json.dumps(result))

    def test_missing_key_and_unsafe_destination_do_not_call_provider(self):
        with patch("backend.connections._post") as post:
            with self.assertRaises(PlanningError):
                test_connection(DEEPSEEK_CONNECTION)
            os.environ["DEEPSEEK_API_KEY"] = self.secret
            with self.assertRaises(PlanningError):
                test_connection({**DEEPSEEK_CONNECTION, "base_url": "http://external.invalid"})
            post.assert_not_called()

    def test_deepseek_execution_and_zip_use_references_without_bundling_key(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        response = {"choices": [{"message": {"content": "A real adapter response"}}]}
        with patch("runtime.providers._post", return_value=response) as post:
            result = complete(DEEPSEEK_CONNECTION, "A system instruction", "A task")
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(result["content"], "A real adapter response")
        workflow = load_template()
        workflow["agents"][0].update(DEEPSEEK_CONNECTION)
        with zipfile.ZipFile(io.BytesIO(build_bundle(workflow))) as archive:
            restored = json.loads(archive.read("workflow.json"))
            self.assertEqual(restored["agents"][0]["credential_ref"], "DEEPSEEK_API_KEY")
            self.assertEqual(restored["agents"][0]["base_url"], "https://api.deepseek.com")
            self.assertIn(b"DEEPSEEK_API_KEY=\n", archive.read(".env.example"))
            self.assertNotIn(".env.local", archive.namelist())
            self.assertTrue(all(self.secret.encode() not in archive.read(item) for item in archive.namelist()))

    def test_balance_error_is_actionable_and_provider_details_stay_private(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        with patch("backend.connections._post", side_effect=ProviderError(self.secret, http_status=402)):
            with self.assertRaises(PlanningError) as result:
                test_connection(DEEPSEEK_CONNECTION)
        self.assertIn("402", str(result.exception))
        self.assertIn("quota", str(result.exception))
        self.assertNotIn(self.secret, str(result.exception))

    def test_status_contains_only_booleans_and_includes_deepseek(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        result = credential_status(self.root)
        self.assertTrue(result["DEEPSEEK_API_KEY"])
        self.assertTrue(all(isinstance(value, bool) for value in result.values()))

    def test_official_gpt6_has_bounded_reasoning_budget_and_compatible_parameter(self):
        os.environ["OPENAI_API_KEY"] = self.secret
        response = {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra"):
            with self.subTest(model=model), patch("backend.connections._post", return_value=response) as post:
                result = test_connection({"provider": "openai", "model": model, "credential_ref": "OPENAI_API_KEY"})
                url, headers, payload, timeout = post.call_args.args
                self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
                self.assertEqual(payload["model"], model)
                self.assertNotIn("max_tokens", payload)
                self.assertEqual(payload["max_completion_tokens"], 512)
                self.assertEqual(payload["reasoning_effort"], "low")
                self.assertEqual(timeout, 30)
                self.assertTrue(result["ok"])

    def test_custom_endpoint_does_not_receive_official_openai_parameters(self):
        os.environ["CUSTOM_API_KEY"] = self.secret
        response = {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
        connection = {"provider": "openai", "model": "gpt-6-astra", "credential_ref": "CUSTOM_API_KEY",
                      "base_url": "https://gateway.example.invalid/v1"}
        with patch("backend.connections._post", return_value=response) as post:
            test_connection(connection)
        payload = post.call_args.args[2]
        self.assertEqual(payload["max_tokens"], 16)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("reasoning_effort", payload)

    def test_chat_rejects_empty_malformed_truncated_refusal_and_tool_results(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        invalid = [None, {}, {"choices": []}, {"choices": [{}]}, {"choices": [None]},
                   {"choices": [{"finish_reason": "stop", "message": None}]},
                   {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]},
                   {"choices": [{"finish_reason": "stop", "message": {"content": ["OK"]}}]}]
        for reason in (None, "length", "content_filter", "tool_calls"):
            invalid.append({"choices": [{"finish_reason": reason, "message": {"content": "OK"}}]})
        for extra in ({"refusal": "No"}, {"tool_calls": [{"id": "unexpected"}]}, {"function_call": {"name": "unexpected"}}):
            invalid.append({"choices": [{"finish_reason": "stop", "message": {"content": "OK", **extra}}]})
        invalid.append({"error": {"message": self.secret}, "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})
        for response in invalid:
            with self.subTest(response=response), patch("backend.connections._post", return_value=response):
                with self.assertRaises(PlanningError) as caught:
                    test_connection(DEEPSEEK_CONNECTION)
                self.assertEqual(caught.exception.status, 502)
                self.assertNotIn(self.secret, str(caught.exception))

    def test_anthropic_requires_completed_text_and_uses_own_auth(self):
        os.environ["ANTHROPIC_API_KEY"] = self.secret
        connection = {"provider": "anthropic", "model": "fixture-model", "credential_ref": "ANTHROPIC_API_KEY"}
        success = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "OK"}]}
        with patch("backend.connections._post", return_value=success) as post:
            self.assertTrue(test_connection(connection)["ok"])
        url, headers, payload, timeout = post.call_args.args
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], self.secret)
        self.assertNotIn("Authorization", headers)
        self.assertEqual(payload["max_tokens"], 16)
        for response in ({"content": [{}]}, {**success, "stop_reason": "max_tokens"},
                         {**success, "stop_reason": "refusal"}, {**success, "content": []},
                         {**success, "content": [{"type": "text", "text": " "}]},
                         {**success, "content": [{"type": "tool_use", "name": "unexpected"}]},
                         {**success, "content": [None]}):
            with self.subTest(response=response), patch("backend.connections._post", return_value=response):
                with self.assertRaises(PlanningError):
                    test_connection(connection)

    def test_malformed_base_urls_are_rejected_before_any_request(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        for base in (42, "https://[invalid", "https://example.invalid:bad", "https://example.invalid:0"):
            with self.subTest(base=base), patch("backend.connections._post") as post:
                with self.assertRaises(PlanningError):
                    test_connection({**DEEPSEEK_CONNECTION, "base_url": base})
                post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
