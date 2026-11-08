"""Pitch requirement contracts with fixed responses, never a live model or user PDF."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from backend.bundle import build_bundle
from backend.planner import PlanningError, plan_workflow, reviewed_task_assignments
from backend.requirements import analyze_requirements
from runtime.engine import Engine
from runtime.validation import validate_workflow
from tests.test_backend import temporary_run
from tests.test_requirements import PLANNER, TEST_ENV, safe_draft


def pitch_analysis():
    return {
        "project_name": "KNOT pitch demo",
        "goal": "Prepare an evidence-backed pitch proposal from supplied materials.",
        "deliverables": ["evidence.csv", "budget.json", "proposal.md"],
        "tasks": [
            {"title": "T01 Evidence", "description": "Prepare the evidence CSV from supplied facts.",
             "acceptance": "Each evidence row is traceable to the supplied materials.",
             "owner": "Jordan Lee", "source_pages": [1]},
            {"title": "T02 Budget", "description": "Prepare the budget JSON from supplied costs.",
             "acceptance": "Budget totals reconcile with the supplied costs.",
             "owner": "Priya Shah", "source_pages": [1]},
            {"title": "T03 Proposal", "description": "Combine the evidence and budget into the proposal.",
             "acceptance": "The proposal agrees with both upstream outputs.",
             "owner": "Alex Morgan", "source_pages": [1]},
        ],
        "constraints": [
            "Exactly three AI tasks and two dependency waves: T01 and T02 run in parallel, then T03.",
            "Alex Morgan personally approves the three deliverables in one human review after T03.",
            "Output collects evidence.csv, budget.json and proposal.md only after human approval; it does no AI work.",
        ],
        "missing_information": [],
    }


def pitch_document():
    analysis = pitch_analysis()
    text = "\n".join(
        [analysis["goal"], *analysis["constraints"]]
        + [f"{task['title']}: {task['description']} Owner: {task['owner']}." for task in analysis["tasks"]]
    )
    return {
        "filename": "pitch-contract.txt", "source_type": "text",
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "page_count": 1,
        "text": text, "pages": [{"number": 1, "text": text}], "warnings": [],
    }


def pitch_workflow():
    draft = safe_draft()
    analysis = pitch_analysis()
    draft["project"].update(
        name=analysis["project_name"], goal=pitch_document()["text"],
        deliverable="; ".join(analysis["deliverables"]),
        members=[{"id": f"member-{index}", "name": task["owner"], "skills": ""}
                 for index, task in enumerate(analysis["tasks"], 1)],
    )
    draft["resources"] = [
        {"id": "requirements-source-pitch", "name": "Pitch source", "path": "inputs/pitch.txt",
         "description": "Fixed source for the regression contract.", "example": False,
         "content": pitch_document()["text"]},
        {"id": "requirements-analysis-pitch", "name": "Reviewed pitch tasks",
         "path": "inputs/pitch-analysis.json", "description": "Three reviewed AI tasks and review constraints.",
         "example": False, "content": json.dumps(analysis)},
    ]
    nodes = {node["id"]: node for node in draft["nodes"]}
    nodes["resources"]["config"]["resource_ids"] = [r["id"] for r in draft["resources"]]
    for index, (node_id, output_format) in enumerate(
        (("research", "csv"), ("analysis", "json"), ("synthesis", "markdown")), 1
    ):
        nodes[node_id]["config"].update(
            owner_id=f"member-{index}", requirement_task_indexes=[index], output_format=output_format,
        )
    nodes["review"]["config"].update(
        owner_id="member-3", instructions="Alex Morgan must personally check and approve all three deliverables."
    )
    nodes["output"]["config"]["mappings"] = [
        {"source_node": node_id, "filename": filename, "format": output_format}
        for node_id, filename, output_format in (
            ("research", "evidence.csv", "csv"), ("analysis", "budget.json", "json"),
            ("synthesis", "proposal.md", "markdown"),
        )
    ]
    for source, target in (("resources", "synthesis"), ("research", "review"),
                           ("analysis", "review"), ("research", "output")):
        draft["edges"].append({"id": f"data-{source}-{target}", "source": source, "target": target,
                               "kind": "data", "source_port": "data-out", "target_port": "data-in"})
    draft["design_notes"] = ["Three AI tasks in two waves; Alex personally approves before final output."]
    return draft


def model_response(workflow):
    return {"content": json.dumps({key: value for key, value in workflow.items()
                                   if key not in ("project", "resources")})}


class PitchRequirementsTests(unittest.TestCase):
    def plan(self, workflow, model_call):
        with patch.dict(os.environ, TEST_ENV):
            return plan_workflow(workflow["project"], workflow["resources"], PLANNER, model_call=model_call)

    def test_analysis_keeps_three_ai_tasks_and_preserves_the_human_review_constraints(self):
        # This verifies the prompt/data contract, not semantic accuracy of a live model.
        document = pitch_document()
        analysis = pitch_analysis()
        original = deepcopy(document)

        def call(_agent, system, prompt, **_kwargs):
            self.assertIn("AI-executable", system)
            self.assertIn("human approval", system)
            self.assertIn("constraints", system)
            self.assertIn("exact", system.lower())
            self.assertEqual(json.loads(prompt.split("\n", 1)[1])["document"], document)
            return {"content": json.dumps(analysis)}

        with patch.dict(os.environ, TEST_ENV):
            result = analyze_requirements(document, PLANNER, model_call=call)
        self.assertEqual(document, original)
        self.assertEqual(result, analysis)
        self.assertEqual(len(result["tasks"]), 3)
        self.assertIn("Alex Morgan personally approves", result["constraints"][1])

    def test_assignment_table_uses_global_indexes_and_exact_member_names(self):
        workflow = pitch_workflow()
        first = workflow["resources"][1]
        tasks = pitch_analysis()["tasks"]
        tasks[0]["owner"] = " jordan LEE "
        tasks.extend([
            {**tasks[0], "title": "Unassigned follow-up", "owner": ""},
            {**tasks[0], "title": "Unmatched owner", "owner": "Jordan"},
        ])
        first["content"] = json.dumps({**pitch_analysis(), "tasks": tasks[:2]})
        workflow["resources"].append({
            **first, "id": "requirements-analysis-second", "path": "inputs/second-analysis.json",
            "content": json.dumps({**pitch_analysis(), "tasks": tasks[2:]}),
        })
        workflow["project"]["members"].append({"id": "member-jordan-duplicate", "name": "Jordan Lee", "skills": ""})
        original = deepcopy(workflow)
        table = reviewed_task_assignments(workflow["project"], workflow["resources"])
        self.assertEqual(table, [
            {"requirement_task_index": 1, "title": "T01 Evidence", "owner": " jordan LEE ",
             "allowed_owner_ids": ["member-1", "member-jordan-duplicate"]},
            {"requirement_task_index": 2, "title": "T02 Budget", "owner": "Priya Shah", "allowed_owner_ids": ["member-2"]},
            {"requirement_task_index": 3, "title": "T03 Proposal", "owner": "Alex Morgan", "allowed_owner_ids": ["member-3"]},
            {"requirement_task_index": 4, "title": "Unassigned follow-up", "owner": "", "allowed_owner_ids": []},
            {"requirement_task_index": 5, "title": "Unmatched owner", "owner": "Jordan", "allowed_owner_ids": []},
        ])
        self.assertEqual(workflow, original)

    def test_repair_removes_gate_mappings_without_changing_reviewed_tasks(self):
        valid = pitch_workflow()
        invalid = deepcopy(valid)
        for node in invalid["nodes"]:
            if node["id"] in ("review", "output"):
                node["config"]["requirement_task_indexes"] = [3]
        original = deepcopy(valid)
        prompts = []
        expected_table = reviewed_task_assignments(valid["project"], valid["resources"])

        def call(_agent, system, prompt, **_kwargs):
            prompts.append(prompt)
            self.assertIn("human_review", system)
            self.assertIn("requirement_task_indexes", system)
            payload = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(payload["reviewed_task_assignments"], expected_table)
            if len(prompts) == 1:
                self.assertEqual(payload["resources"], valid["resources"])
                return model_response(invalid)
            self.assertEqual(payload["original_input"], {"project": valid["project"], "resources": valid["resources"]})
            self.assertEqual(payload["previous_draft"]["edges"], invalid["edges"])
            self.assertEqual({issue.get("node_id") for issue in payload["errors"]}, {"review", "output"})
            return model_response(valid)

        result = self.plan(valid, call)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(valid, original)
        self.assertEqual(result["resources"], original["resources"])
        self.assertEqual(result["project"], original["project"])
        self.assertEqual(result["edges"], original["edges"])
        self.assertEqual(sum(node["type"] == "agent_task" for node in result["nodes"]), 3)
        for node in result["nodes"]:
            if node["type"] in ("human_review", "output"):
                self.assertNotIn("requirement_task_indexes", node["config"])
        self.assertFalse([issue for issue in validate_workflow(result) if issue["severity"] == "error"])

    def test_old_fourth_human_task_is_not_silently_dropped_or_treated_as_covered(self):
        draft = pitch_workflow()
        analysis = pitch_analysis()
        analysis["tasks"].append({
            "title": "Personal approval and delivery", "description": "Alex personally approves; Output collects the existing files.",
            "acceptance": "Alex's explicit approval occurs before final delivery.", "owner": "Alex Morgan", "source_pages": [1],
        })
        draft["resources"][1]["content"] = json.dumps(analysis)
        for node in draft["nodes"]:
            if node["id"] in ("review", "output"):
                node["config"]["requirement_task_indexes"] = [4]
        original = deepcopy(draft)
        prompts = []

        def call(_agent, _system, prompt, **_kwargs):
            prompts.append(prompt)
            payload = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(payload["reviewed_task_assignments"][-1], {
                "requirement_task_index": 4, "title": "Personal approval and delivery", "owner": "Alex Morgan",
                "allowed_owner_ids": ["member-3"],
            })
            if len(prompts) > 1:
                self.assertEqual(payload["original_input"]["resources"], original["resources"])
                self.assertEqual(payload["previous_draft"]["edges"], original["edges"])
            return model_response(draft)

        with self.assertRaises(PlanningError) as raised:
            self.plan(draft, call)
        self.assertEqual(raised.exception.status, 422)
        self.assertIn("已确认的任务列表", str(raised.exception))
        self.assertIn("重新分析并确认", str(raised.exception))
        self.assertIn("无需因此修改需求文件", str(raised.exception))
        self.assertEqual(len(prompts), 3)
        self.assertEqual(draft, original)
        issues = raised.exception.issues
        self.assertEqual({issue.get("node_id") for issue in issues if issue.get("node_id")}, {"review", "output"})
        self.assertTrue(any("Reviewed task 4 needs exactly one agent_task" in issue["message"] for issue in issues))

    def test_three_task_export_waits_for_the_named_human_before_all_final_files(self):
        draft = pitch_workflow()
        planned = self.plan(draft, lambda *_a, **_k: model_response(draft))
        with temporary_run("pitch-review-contract-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(planned))) as archive:
                archive.extractall(root)
                self.assertEqual(json.loads(archive.read("workflow.json")), planned)
            engine = Engine(planned, directory, mode="mock")
            self.assertEqual(engine.run()["status"], "waiting_review")
            for filename in pitch_analysis()["deliverables"]:
                self.assertFalse((root / "results" / filename).exists())
            with self.assertRaises(PermissionError):
                engine.resume("review", "approve", "member-1")
            engine.resume("review", "approve", "member-3")
            self.assertEqual(engine.run()["status"], "completed")
            for filename in pitch_analysis()["deliverables"]:
                self.assertTrue((root / "results" / filename).is_file())

    def test_rejecting_pitch_review_blocks_all_three_final_files(self):
        draft = pitch_workflow()
        planned = self.plan(draft, lambda *_a, **_k: model_response(draft))
        with temporary_run("pitch-rejected-contract-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(planned))) as archive:
                archive.extractall(root)
            engine = Engine(planned, directory, mode="mock")
            self.assertEqual(engine.run()["status"], "waiting_review")
            engine.resume("review", "reject", "member-3")
            result = engine.run()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["nodes"]["output"]["status"], "blocked")
            for filename in pitch_analysis()["deliverables"]:
                self.assertFalse((root / "results" / filename).exists())


if __name__ == "__main__":
    unittest.main()
