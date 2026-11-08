"""Local example helper boundaries; all keys are fixtures, no model calls."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_owner_example as helper


class OwnerExampleLauncherTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="owner-example-launcher-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.editor = self.root / "fixture-editor"
        self.package = self.root / "extracted-package"
        self.editor.mkdir()
        self.package.mkdir()
        self.patch_root = patch.object(helper, "EDITOR_ROOT", self.editor)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.patch_env = patch.dict(os.environ, {"PATH": "fixture-original-path"}, clear=True)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.alice_key = "fixture-alice-local-value"
        self.bob_key = "fixture-bob-local-value"
        (self.editor / ".env.local").write_text(
            "KNOT_DEMO_ALICE_API_KEY=" + self.alice_key + "\n"
            "KNOT_DEMO_BOB_API_KEY=" + self.bob_key + "\n", encoding="utf-8")
        (self.editor / ".env").write_text(
            "KNOT_DEMO_BOB_API_KEY=fixture-bob-fallback-value\n", encoding="utf-8")
        self.workflow = json.loads((Path(__file__).resolve().parents[1]
                                    / "examples/owner-api-smoke.json").read_text(encoding="utf-8"))
        for member in self.workflow["project"]["members"]:
            member["connection"]["model"] = "fixture-" + member["id"]
        (self.package / "workflow.json").write_text(json.dumps(self.workflow), encoding="utf-8")
        (self.package / "knot.json").write_text(json.dumps({"backend": "opencode"}), encoding="utf-8")

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = helper.main([str(self.package), *args])
        return code, output.getvalue(), errors.getvalue()

    def test_editor_keys_and_local_binary_are_used_without_copying_keys(self):
        binary_dir = self.editor / ".tools/opencode-cli/node_modules/@opencode/cli/bin"
        binary_dir.mkdir(parents=True)
        (binary_dir / ("opencode.exe" if os.name == "nt" else "opencode")).write_text("fixture", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in self.package.iterdir()}

        def observe(options):
            self.assertEqual(os.environ["KNOT_DEMO_ALICE_API_KEY"], self.alice_key)
            self.assertEqual(os.environ["KNOT_DEMO_BOB_API_KEY"], self.bob_key)
            self.assertEqual(os.environ["PATH"], str(binary_dir) + os.pathsep + "fixture-original-path")
            self.assertEqual(options, ["--root", str(self.package.resolve()), "--workflow",
                                       str((self.package / "workflow.json").resolve()),
                                       "--interactive", "--plain"])
            return 23

        with patch.object(helper, "run_workflow", side_effect=observe) as execute:
            code, output, errors = self.invoke("--plain")
        self.assertEqual(code, 23, errors)
        execute.assert_called_once()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.package.iterdir()})
        self.assertNotIn(self.alice_key, output + errors)
        self.assertNotIn(self.bob_key, output + errors)

    def test_existing_environment_takes_precedence_and_validation_starts_no_engine(self):
        existing = "fixture-alice-existing-environment"
        os.environ["KNOT_DEMO_ALICE_API_KEY"] = existing
        with patch("run.check_backend", return_value={"available": True, "version": "fixture"}) as backend, \
                patch("run.Engine") as engine, patch("run.run_engine") as execute, \
                patch("builtins.input") as prompt:
            code, output, errors = self.invoke("--validate")
        self.assertEqual(code, 0, output + errors)
        backend.assert_called_once_with("opencode")
        engine.assert_not_called()
        execute.assert_not_called()
        prompt.assert_not_called()
        self.assertEqual(os.environ["KNOT_DEMO_ALICE_API_KEY"], existing)
        self.assertEqual(os.environ["KNOT_DEMO_BOB_API_KEY"], self.bob_key)
        self.assertNotIn(existing, output + errors)
        self.assertNotIn(self.bob_key, output + errors)
        self.assertEqual({p.name for p in self.package.iterdir()}, {"workflow.json", "knot.json"})

    def test_missing_workflow_rejects_before_loading_any_keys(self):
        (self.package / "workflow.json").unlink()
        with patch.object(helper, "load_env") as load, patch.object(helper, "run_workflow") as execute:
            code, _, errors = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("workflow.json", errors)
        load.assert_not_called()
        execute.assert_not_called()
        self.assertNotIn("KNOT_DEMO_ALICE_API_KEY", os.environ)
        self.assertEqual(os.environ["PATH"], "fixture-original-path")

    def test_other_backend_rejects_before_loading_any_keys(self):
        (self.package / "knot.json").write_text(json.dumps({"backend": "codex"}), encoding="utf-8")
        with patch.object(helper, "load_env") as load, patch.object(helper, "run_workflow") as execute:
            code, _, errors = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("OpenCode", errors)
        load.assert_not_called()
        execute.assert_not_called()
        self.assertNotIn("KNOT_DEMO_BOB_API_KEY", os.environ)

    def test_retry_is_explicit_and_forwards_only_requested_options(self):
        with patch.object(helper, "run_workflow", return_value=0) as execute:
            code, _, errors = self.invoke("--retry-failed")
        self.assertEqual(code, 0, errors)
        self.assertIn("--retry-failed", execute.call_args.args[0])
        self.assertNotIn("--validate", execute.call_args.args[0])
        self.assertEqual(os.environ["PATH"], "fixture-original-path")
        with patch.object(helper, "load_env") as load, patch.object(helper, "run_workflow") as execute, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            helper.main([str(self.package), "--retry-failed", "--validate"])
        self.assertEqual(raised.exception.code, 2)
        load.assert_not_called()
        execute.assert_not_called()

    def test_error_messages_redact_loaded_fixture_keys(self):
        with patch.object(helper, "run_workflow", side_effect=ValueError("fixture failure " + self.bob_key)):
            code, output, errors = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("[REDACTED]", errors)
        self.assertNotIn(self.alice_key, output + errors)
        self.assertNotIn(self.bob_key, output + errors)
        self.assertFalse((self.package / ".env").exists())


if __name__ == "__main__":
    unittest.main()
