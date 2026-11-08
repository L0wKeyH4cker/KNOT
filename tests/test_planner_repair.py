"""Planner graph repair with fixed model responses; no provider requests."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from backend.bundle import build_bundle
from backend.planner import PlanningError, plan_workflow
from runtime.engine import Engine
from runtime.validation import validate_workflow
from tests.test_backend import temporary_run, valid_ai_draft
from tests.test_runtime import branch_workflow, node


def edge(source, target, kind="control", eid=None):
    return {"id": eid or f"{kind}-{source}-{target}", "source": source, "target": target,
            "kind": kind, "source_port": "out" if kind == "control" else "data-out",
            "target_port": "in" if kind == "control" else "data-in"}


def detached_resources():
    draft = valid_ai_draft()
    draft["edges"] = [e for e in draft["edges"] if e["id"] not in ("control-start-resources", "control-resources-parallel")]
    draft["edges"].append(edge("start", "parallel"))
    return draft


class PlannerRepairTests(unittest.TestCase):
    def plan(self, draft, call=None):
        planner = {"provider": "openai", "model": "fixture", "credential_ref": "KNOT_REPAIR_TEST_KEY"}
        with patch.dict(os.environ, {"KNOT_REPAIR_TEST_KEY": "fixture-planner-repair-no-live-api"}):
            return plan_workflow(draft["project"], draft["resources"], planner,
                                 model_call=call or (lambda *_a, **_k: {"content": json.dumps(draft)}))

    def test_one_or_two_root_resources_get_only_the_missing_control_edges(self):
        for count in (1, 2):
            with self.subTest(count=count):
                draft = detached_resources()
                if count == 2:
                    second = deepcopy(next(n for n in draft["nodes"] if n["id"] == "resources"))
                    second["id"] = "requirements-analysis"
                    draft["nodes"].append(second)
                    draft["edges"].append(edge(second["id"], "research", "data"))
                original = deepcopy(draft)
                calls = []

                def fixed(*args, **kwargs):
                    calls.append(1)
                    return {"content": json.dumps(draft)}

                result = self.plan(draft, fixed)
                self.assertEqual(len(calls), 1)
                self.assertEqual(draft, original)
                self.assertEqual(result["nodes"], draft["nodes"])
                self.assertEqual(result["edges"][:len(draft["edges"])], draft["edges"])
                additions = result["edges"][len(draft["edges"]):]
                self.assertEqual(len(additions), count)
                for e in additions:
                    self.assertEqual((e["source"], e["kind"], e["source_port"], e["target_port"]),
                                     ("start", "control", "out", "in"))
                self.assertFalse([i for i in validate_workflow(result) if i["severity"] == "error"])
                self.assertEqual(self.plan(result), result, "Replanning must not duplicate repairs")

    def test_repair_edge_ids_do_not_collide(self):
        draft = detached_resources()
        draft["edges"][0]["id"] = "auto-start-resource-1"
        result = self.plan(draft)
        ids = [e["id"] for e in result["edges"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("auto-start-resource-2", ids)

    def test_task_review_and_output_are_never_automatically_attached_to_start(self):
        for nid in ("research", "review", "output"):
            with self.subTest(node=nid):
                draft = valid_ai_draft()
                draft["edges"] = [e for e in draft["edges"] if not (e["target"] == nid and e["kind"] == "control")]
                prompts = []

                def fixed(_agent, _system, prompt, **_kwargs):
                    prompts.append(prompt)
                    return {"content": json.dumps(draft)}

                with self.assertRaises(PlanningError) as raised:
                    self.plan(draft, fixed)
                self.assertEqual(len(prompts), 3)
                self.assertTrue(any(i.get("node_id") == nid and i["code"] == "unreachable"
                                    for i in raised.exception.issues))
                for prompt in prompts[1:]:
                    repair = json.loads(prompt.split("\n", 1)[1])
                    self.assertEqual(repair["previous_draft"]["edges"], draft["edges"])

    def test_resources_with_existing_dependencies_keep_their_gates(self):
        for kind in ("control", "data"):
            with self.subTest(kind=kind):
                draft = detached_resources()
                gate = {"id": "resource-gate", "type": "parallel", "label": "Gate",
                        "position": {"x": 100, "y": 700}, "config": {}}
                draft["nodes"].append(gate)
                draft["edges"].append(edge(gate["id"], "resources", kind))
                prompts = []

                def fixed(_agent, _system, prompt, **_kwargs):
                    prompts.append(prompt)
                    return {"content": json.dumps(draft)}

                with self.assertRaises(PlanningError):
                    self.plan(draft, fixed)
                repair = json.loads(prompts[1].split("\n", 1)[1])
                self.assertEqual(repair["previous_draft"]["edges"], draft["edges"])

    def test_resource_control_outputs_cannot_activate_an_unselected_branch(self):
        draft = branch_workflow()
        draft["agents"][0]["credential_ref"] = "OPENAI_API_KEY"
        draft["design_notes"] = ["Keep condition gates."]
        for item in draft["nodes"]:
            item["config"].pop("mock_delay_ms", None)
        draft["resources"] = [{"id": "r", "name": "Brief", "path": "inputs/brief.txt",
                               "description": "Brief", "example": False, "content": "Brief"}]
        draft["nodes"].append(node("resources", "shared_resource", resource_ids=["r"]))
        draft["edges"].extend([edge("resources", "right"), edge("resources", "right", "data")])
        prompts = []

        def fixed(_agent, _system, prompt, **_kwargs):
            prompts.append(prompt)
            return {"content": json.dumps(draft)}

        with self.assertRaises(PlanningError) as raised:
            self.plan(draft, fixed)
        self.assertEqual([(i["code"], i.get("node_id")) for i in raised.exception.issues],
                         [("unreachable", "resources")])
        for prompt in prompts[1:]:
            repair = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(repair["previous_draft"]["edges"], draft["edges"])

    def test_repair_prompt_contains_precise_errors_previous_draft_and_original_input(self):
        valid = valid_ai_draft()
        invalid = deepcopy(valid)
        invalid["edges"] = [e for e in invalid["edges"] if e["id"] != "control-parallel-research"]
        calls = []

        def repaired(_agent, _system, prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return {"content": json.dumps(invalid)}
            payload = json.loads(prompt.split("\n", 1)[1])
            self.assertIn({"severity": "error", "code": "unreachable", "node_id": "research",
                           "message": "Connect this node to Start with execution connections"}, payload["errors"])
            self.assertEqual(payload["previous_draft"], {k: v for k, v in invalid.items() if k not in ("project", "resources")})
            self.assertEqual(payload["original_input"], {"project": valid["project"], "resources": valid["resources"]})
            return {"content": json.dumps(valid)}

        self.assertEqual(self.plan(valid, repaired), valid)
        self.assertEqual(len(calls), 2)

    def test_malformed_or_secret_output_is_not_resubmitted(self):
        marker = "sk-" + "x" * 32
        secret_draft = valid_ai_draft()
        secret_draft["design_notes"] = [marker]
        for bad in ("not JSON private-provider-body", json.dumps(secret_draft)):
            with self.subTest(secret=marker in bad):
                prompts = []

                def fixed(_agent, _system, prompt, **_kwargs):
                    prompts.append(prompt)
                    return {"content": bad}

                with self.assertRaises(PlanningError) as raised:
                    self.plan(valid_ai_draft(), fixed)
                self.assertEqual(len(prompts), 3)
                for prompt in prompts[1:]:
                    self.assertNotIn(marker, prompt)
                    self.assertNotIn("private-provider-body", prompt)
                    self.assertIsNone(json.loads(prompt.split("\n", 1)[1])["previous_draft"])
                self.assertNotIn(marker, json.dumps(raised.exception.issues))

    def test_invalid_topology_and_capabilities_still_fail(self):
        for problem in ("cycle", "extra_start", "wrong_ports", "duplicate_id", "permissions", "malformed"):
            with self.subTest(problem=problem):
                draft = detached_resources()
                if problem == "cycle":
                    draft["edges"].append(edge("synthesis", "research"))
                elif problem == "extra_start":
                    draft["nodes"].append({**deepcopy(draft["nodes"][0]), "id": "start-2"})
                elif problem == "wrong_ports":
                    draft["edges"][0]["target_port"] = "data-in"
                elif problem == "duplicate_id":
                    draft["nodes"].append(deepcopy(draft["nodes"][0]))
                elif problem == "permissions":
                    draft["nodes"][3]["config"]["permissions"]["read"] = ["inputs/"]
                else:
                    draft["nodes"][0]["config"] = []
                with self.assertRaises(PlanningError):
                    self.plan(draft)

    def test_repaired_export_runs_but_still_stops_before_human_review(self):
        repaired = self.plan(detached_resources())
        with temporary_run("repaired-planner-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(repaired))) as archive:
                archive.extractall(root)
            engine = Engine(repaired, directory, mode="mock")
            self.assertEqual(engine.run()["status"], "waiting_review")
            self.assertFalse((root / "results/report.md").exists())
            engine.resume("review", "approve", "member-3")
            self.assertEqual(engine.run()["status"], "completed")
            self.assertTrue((root / "results/report.md").is_file())


if __name__ == "__main__":
    unittest.main()
