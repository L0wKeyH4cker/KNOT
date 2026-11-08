"""Black-box acceptance checks against a ZIP unpacked into a fresh directory."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from backend.bundle import build_bundle
from backend.template import load_template


class DeliveryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Stay in the authorized workspace, while the subprocess only sees the extracted bundle.
        self.scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="knot-delivery-", dir=self.scratch)
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(self.scratch.resolve()))
        self.workflow = load_template()
        for node in self.workflow["nodes"]:
            if node["type"] == "agent_task":
                node["config"]["mock_delay_ms"] = 20

    def tearDown(self):
        self.temporary.cleanup()

    def unpack(self, workflow, folder="run"):
        target = self.root / folder
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(build_bundle(workflow))) as archive:
            self.assertEqual(json.loads(archive.read("workflow.json")), workflow)
            self.assertIn("runtime/engine.py", archive.namelist())
            self.assertIn("start.bat", archive.namelist())
            self.assertIn("start.sh", archive.namelist())
            self.assertNotIn("server.py", archive.namelist())
            archive.extractall(target)
        return target

    def run_cli(self, folder, *arguments):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "run.py", "--mode", "mock", *arguments],
            cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=environment,
        )
        return result

    def test_portable_zip_waits_then_delivers_after_explicit_approval(self):
        folder = self.unpack(self.workflow)
        paused = self.run_cli(folder)
        self.assertEqual(paused.returncode, 2, paused.stdout + paused.stderr)
        before = json.loads((folder / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(before["nodes"]["review"]["status"], "waiting_review")
        self.assertFalse((folder / "results/report.md").exists())
        self.assertFalse((folder / "results/summary.csv").exists())
        resumed = self.run_cli(folder, "--resume", "--review", "review", "--decision", "approve", "--reviewer", "member-3")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        report = (folder / "results/report.md").read_text(encoding="utf-8")
        summary = (folder / "results/summary.csv").read_text(encoding="utf-8")
        self.assertIn("MOCK", report)
        self.assertIn("share_percent", summary)
        self.assertIn("Walk,12,30", summary)
        after = json.loads((folder / "logs/run-state.json").read_text(encoding="utf-8"))
        for node_id in ("research", "analysis", "synthesis"):
            self.assertEqual(after["nodes"][node_id], before["nodes"][node_id], "Resume reran an already completed task")

    def test_rejecting_review_blocks_final_files(self):
        folder = self.unpack(self.workflow)
        self.assertEqual(self.run_cli(folder).returncode, 2)
        result = self.run_cli(folder, "--resume", "--review", "review", "--decision", "reject", "--reviewer", "member-3")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((folder / "results/report.md").exists())
        self.assertFalse((folder / "results/summary.csv").exists())

    def test_inserting_review_into_final_control_path_changes_runtime(self):
        base = deepcopy(self.workflow)
        base["nodes"] = [node for node in base["nodes"] if node["id"] != "review"]
        base["edges"] = [edge for edge in base["edges"] if "review" not in (edge["source"], edge["target"])]
        base["edges"].append({"id": "direct-delivery", "source": "synthesis", "target": "output", "source_port": "out", "target_port": "in", "kind": "control"})
        original_folder = self.unpack(base, "before-edit")
        original = self.run_cli(original_folder)
        self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
        self.assertTrue((original_folder / "results/report.md").is_file())

        edited = deepcopy(base)
        edited["nodes"].append({"id": "added-review", "type": "human_review", "label": "Added on the canvas", "position": {"x": 1600, "y": 300}, "config": {"owner_id": "member-1", "instructions": "Verify the report before writing final files."}})
        next(edge for edge in edited["edges"] if edge["id"] == "direct-delivery")["target"] = "added-review"
        edited["edges"].append({"id": "review-to-output", "source": "added-review", "target": "output", "source_port": "out", "target_port": "in", "kind": "control"})
        edited_folder = self.unpack(edited, "after-edit")
        result = self.run_cli(edited_folder)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((edited_folder / "results/report.md").exists())
        state = json.loads((edited_folder / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["nodes"]["added-review"]["status"], "waiting_review")

    def test_resume_rejects_a_changed_workflow(self):
        folder = self.unpack(self.workflow)
        self.assertEqual(self.run_cli(folder).returncode, 2)
        changed = deepcopy(self.workflow)
        next(node for node in changed["nodes"] if node["id"] == "synthesis")["config"]["instructions"] = "Changed after the run paused"
        (folder / "workflow.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        result = self.run_cli(folder, "--resume", "--review", "review", "--decision", "approve", "--reviewer", "member-3")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((folder / "results/report.md").exists())

    def test_multiple_review_gates_each_require_explicit_approval(self):
        workflow = deepcopy(self.workflow)
        start = next(n for n in workflow["nodes"] if n["id"] == "start")
        task = next(n for n in workflow["nodes"] if n["id"] == "synthesis")
        review = next(n for n in workflow["nodes"] if n["id"] == "review")
        review_a, review_b = deepcopy(review), deepcopy(review)
        review_a["id"], review_b["id"] = "review-a", "review-b"
        output = next(n for n in workflow["nodes"] if n["id"] == "output")
        output["config"]["mappings"] = [{"source_node": "synthesis", "filename": "report.md", "format": "markdown"}]
        workflow["nodes"] = [start, review_a, review_b, task, output]
        pairs = [("start", "review-a"), ("start", "review-b"), ("review-a", "synthesis"), ("review-b", "synthesis"), ("synthesis", "output")]
        workflow["edges"] = [{"id": f"edge-{i}", "source": source, "target": target, "source_port": "out", "target_port": "in", "kind": "control"} for i, (source, target) in enumerate(pairs)]
        workflow["edges"].append({"id": "output-data", "source": "synthesis", "target": "output", "source_port": "data-out", "target_port": "data-in", "kind": "data"})
        folder = self.unpack(workflow)
        self.assertEqual(self.run_cli(folder).returncode, 2)
        self.assertEqual(self.run_cli(folder, "--resume", "--review", "review-a", "--decision", "approve", "--reviewer", "member-3").returncode, 2)
        self.assertFalse((folder / "results/report.md").exists())
        state = json.loads((folder / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["nodes"]["review-a"]["status"], "succeeded")
        self.assertEqual(state["nodes"]["review-b"]["status"], "waiting_review")
        self.assertEqual(self.run_cli(folder, "--resume", "--review", "review-b", "--decision", "approve", "--reviewer", "member-3").returncode, 0)
        self.assertTrue((folder / "results/report.md").exists())

    def test_output_cannot_fabricate_a_skipped_source(self):
        workflow = deepcopy(self.workflow)
        start = next(n for n in workflow["nodes"] if n["id"] == "start")
        task = next(n for n in workflow["nodes"] if n["id"] == "synthesis")
        condition = {"id": "condition", "type": "condition", "label": "False branch", "position": {"x": 400, "y": 200}, "config": {"source_node": "start", "field": "data.project.name", "operator": "eq", "value": "different-name"}}
        output = next(n for n in workflow["nodes"] if n["id"] == "output")
        output["config"]["mappings"] = [{"source_node": "synthesis", "filename": "report.md", "format": "markdown"}]
        workflow["nodes"] = [start, condition, task, output]
        workflow["edges"] = [
            {"id": "c1", "source": "start", "target": "condition", "source_port": "out", "target_port": "in", "kind": "control"},
            {"id": "c2", "source": "condition", "target": "synthesis", "source_port": "true", "target_port": "in", "kind": "control"},
            {"id": "c3", "source": "condition", "target": "output", "source_port": "false", "target_port": "in", "kind": "control"},
            {"id": "c4", "source": "synthesis", "target": "output", "source_port": "out", "target_port": "in", "kind": "control"},
            {"id": "d1", "source": "start", "target": "condition", "source_port": "data-out", "target_port": "data-in", "kind": "data"},
            {"id": "d2", "source": "synthesis", "target": "output", "source_port": "data-out", "target_port": "data-in", "kind": "data"},
        ]
        folder = self.unpack(workflow)
        result = self.run_cli(folder)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((folder / "results/report.md").exists())
        state = json.loads((folder / "logs/run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["nodes"]["synthesis"]["status"], "skipped")
        self.assertIn("skipped or unavailable", state["nodes"]["output"]["error"])

    @unittest.skipUnless(os.name == "nt", "Windows launcher check runs on Windows")
    def test_windows_launcher_prepares_environment_and_reaches_review(self):
        folder = self.unpack(self.workflow)
        launched = subprocess.run(
            ["cmd.exe", "/d", "/c", "start.bat", "--mode", "mock"], cwd=folder,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        self.assertEqual(launched.returncode, 2, launched.stdout + launched.stderr)
        self.assertTrue((folder / ".venv/Scripts/python.exe").is_file())
        self.assertTrue((folder / ".env").is_file())
        self.assertFalse((folder / "results/report.md").exists())


if __name__ == "__main__":
    unittest.main()
