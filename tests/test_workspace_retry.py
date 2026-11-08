"""Failed drafts stay intact and re-enter handoffs only after normal collection."""
import json
from pathlib import Path
import unittest

from runtime.workspace import LocalWorkspace, task_prompt
from runtime.coding import COMPLETION_CRITERIA, RESULT_INSTRUCTIONS, _result_object
from tests.test_backend import temporary_run, valid_ai_draft


class WorkspaceRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_run("workspace-retry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = valid_ai_draft()
        self.node = next(n for n in self.workflow["nodes"] if n["id"] == "research")
        self.ws = LocalWorkspace(self.root, self.workflow)

    def test_unchanged_failed_draft_is_collected_against_original_inputs(self):
        seed = self.root / "workspace"
        seed.mkdir()
        (seed / "obsolete.txt").write_text("old", encoding="utf-8")
        work, _, _ = self.ws.prepare(self.node, {})
        (work / "evidence.csv").write_text("quarter,value\n2025Q4,10\n", encoding="utf-8")
        (work / "obsolete.txt").unlink()
        context = work / ".knot-context/input-data.json"
        context.write_text('{"stale":true}', encoding="utf-8")
        previous = work.relative_to(self.root).as_posix()

        new, before, inherited = self.ws.prepare(self.node, {}, retry_from=previous)
        self.assertNotEqual(new, work)
        self.assertEqual((work / "evidence.csv").read_bytes(), (new / "evidence.csv").read_bytes())
        self.assertFalse((new / "obsolete.txt").exists())
        self.assertEqual(json.loads((new / ".knot-context/input-data.json").read_text()), {})
        self.assertEqual(context.read_text(), '{"stale":true}')
        changes, modified = self.ws.collect(self.node, new, before, inherited)
        self.assertEqual(set(modified), {"evidence.csv", "obsolete.txt"})
        self.assertEqual(changes["evidence.csv"]["node"], "research")
        self.assertIsNone(changes["obsolete.txt"]["hash"])

    def test_retry_rejects_other_tasks_or_escaped_paths_and_preserves_original(self):
        work, _, _ = self.ws.prepare(self.node, {})
        other = next(n for n in self.workflow["nodes"] if n["id"] == "analysis")
        other_work, _, _ = self.ws.prepare(other, {})
        for path in (other_work.relative_to(self.root).as_posix(), "../work", ".knot/tasks/unknown/work"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.ws.prepare(self.node, {}, retry_from=path)
        self.assertTrue(work.is_dir())
        self.assertTrue(other_work.is_dir())

    def test_failed_draft_is_still_checked_for_credentials(self):
        work, _, _ = self.ws.prepare(self.node, {})
        (work / "bad.txt").write_text("sk-" + "x" * 32, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "credential"):
            self.ws.prepare(self.node, {}, retry_from=work.relative_to(self.root).as_posix())

    def test_partial_prepare_restores_missing_inherited_files(self):
        seed = self.root / "workspace"
        seed.mkdir()
        (seed / "first.txt").write_text("first", encoding="utf-8")
        (seed / "second.txt").write_text("second", encoding="utf-8")
        self.ws.initialize()
        relative = f".knot/tasks/{self.ws.names[self.node['id']]}/work"
        partial = self.ws.path(relative)
        partial.mkdir(parents=True)
        (partial / "first.txt").write_text("first", encoding="utf-8")
        work, baseline, inherited = self.ws.prepare(self.node, {}, retry_from=relative)
        self.assertEqual((work / "second.txt").read_text(), "second")
        changes, modified = self.ws.collect(self.node, work, baseline, inherited)
        self.assertEqual(changes, {})
        self.assertEqual(modified, [])

    def test_completion_guidance_is_shared_but_blocked_results_are_not_overridden(self):
        agent = next(a for a in self.workflow["agents"] if a["id"] == self.node["config"]["agent_id"])
        self.assertIn(COMPLETION_CRITERIA, task_prompt(self.workflow, self.node, agent))
        self.assertIn(COMPLETION_CRITERIA, RESULT_INSTRUCTIONS)
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            _result_object({"status": "blocked", "content": "Files created; a mandatory check remains unmet", "data": {}})
        result = _result_object({"status": "completed", "content": "Official web evidence collected; Python offline checks passed; HTTP failed",
                                 "data": {"collection_method": "web"}, "checks": ["python validate.py"]})
        self.assertEqual(result["data"]["collection_method"], "web")


if __name__ == "__main__":
    unittest.main()
