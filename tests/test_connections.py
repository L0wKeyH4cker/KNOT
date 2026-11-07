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
        self.directory = tempfile.TemporaryDirectory()
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
        (self.root / ".env.local").symlink_to(target)
        with self.assertRaises(PlanningError):
            save_credential(self.root, "DEEPSEEK_API_KEY", self.secret)
        self.assertEqual(target.read_text(), "original")

    def test_deepseek_uses_compatible_endpoint_and_bounded_generic_prompt(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        with patch("backend.connections._post", return_value={"choices": [{"message": {"content": "OK"}}]}) as post:
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
        self.assertIn("额度不足", str(result.exception))
        self.assertNotIn(self.secret, str(result.exception))

    def test_status_contains_only_booleans_and_includes_deepseek(self):
        os.environ["DEEPSEEK_API_KEY"] = self.secret
        result = credential_status(self.root)
        self.assertTrue(result["DEEPSEEK_API_KEY"])
        self.assertTrue(all(isinstance(value, bool) for value in result.values()))


if __name__ == "__main__":
    unittest.main()
