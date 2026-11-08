"""Owner/model monitoring is useful without exposing a connection or its key."""
import json
from pathlib import Path
import unittest

from runtime.monitor import cell_width, render_dashboard
from runtime.registry import list_runs
from tests.test_backend import temporary_run
from tests.test_monitor import NOW, sample


class OwnerMonitorTests(unittest.TestCase):
    def test_owner_and_model_survive_registry_projection_without_extra_fields(self):
        for progress in (False, True):
            with self.subTest(progress=progress), temporary_run("owner-monitor-") as directory:
                root = Path(directory)
                (root / "logs").mkdir()
                state = sample()
                state["execution"] = {"backend": "opencode", "model": ""}
                state["nodes"]["right"].update({
                    "owner_id": "member-b", "owner_name": "Member B", "model": "owner-b-model", "provider": "anthropic",
                    "credential_ref": "MEMBER_B_API_KEY", "api_key": "private-monitor-value",
                    "connection": {"key": "private-monitor-value"}, "unrecognized": "private-extra-field",
                })
                (root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
                if progress:
                    (root / "logs/run-state.progress.json").write_text(json.dumps(state), encoding="utf-8")
                run = list_runs(root / "registry", roots=[root])[0]
                node = run["nodes"]["right"]
                for key in ("owner_id", "owner_name", "model", "provider"):
                    self.assertEqual(node[key], state["nodes"]["right"][key])
                for key in ("credential_ref", "api_key", "connection", "unrecognized"):
                    self.assertNotIn(key, node)
                rendered = json.dumps(run)
                self.assertNotIn("private-monitor-value", rendered)
                self.assertNotIn("private-extra-field", rendered)
                frame = render_dashboard([run], selected_task=1, now=NOW)
                self.assertIn("Owner: Member B", frame)
                self.assertIn("Model: anthropic / owner-b-model", frame)
                self.assertIn("per-owner models", frame)
                self.assertNotIn("assistant default", frame)

    def test_registry_filters_bad_types_and_sanitizes_routing_labels(self):
        with temporary_run("owner-monitor-labels-") as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            state = sample()
            state["nodes"]["left"].update({"owner_name": {"private": "nested-value"}, "provider": ["private-provider"], "model": 42})
            state["nodes"]["right"].update({"owner_name": "Alice\x1b[2J", "provider": "openai" * 100,
                                              "model": "model\x1b]0;bad-title\x07 API_KEY=hidden-value " + "x" * 400})
            (root / "logs/run-state.json").write_text(json.dumps(state), encoding="utf-8")
            run = list_runs(root / "registry", roots=[root])[0]
            for key in ("owner_name", "provider", "model"):
                self.assertNotIn(key, run["nodes"]["left"])
            node = run["nodes"]["right"]
            self.assertEqual(node["owner_name"], "Alice")
            self.assertLessEqual(len(node["model"]), 200)
            self.assertLessEqual(len(node["provider"]), 60)
            rendered = json.dumps(run)
            self.assertNotIn("hidden-value", rendered)
            self.assertNotIn("bad-title", rendered)
            self.assertNotIn("\\u001b", rendered)

    def test_routing_details_fit_normal_and_compact_terminals(self):
        run = sample()
        run["execution"] = {"backend": "opencode", "model": ""}
        run["nodes"]["right"].update({"owner_name": "小王", "model": "model-a", "provider": "openai",
                                         "connection": {"api_key": "private-value"}})
        for width, height in ((40, 14), (68, 23), (80, 24), (100, 32)):
            with self.subTest(width=width, height=height):
                frame = render_dashboard([run], selected_task=1, now=NOW, width=width, height=height)
                self.assertIn("Owner: 小王", frame)
                self.assertIn("Model: openai / model-a", frame)
                self.assertNotIn("private-value", frame)
                self.assertLessEqual(len(frame.splitlines()), height)
                self.assertTrue(all(cell_width(line) <= width for line in frame.splitlines()))


if __name__ == "__main__":
    unittest.main()
