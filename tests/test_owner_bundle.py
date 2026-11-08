"""Portable OpenCode owner connections and credential-free workspace handoffs."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

from backend.bundle import BundleError, build_bundle, reject_secrets
from backend.template import load_template
from runtime.workspace import LocalWorkspace, task_prompt
from tests.test_backend import temporary_run


def owner_workflow():
    workflow = load_template()
    for index, member in enumerate(workflow["project"]["members"], 1):
        member["connection"] = {
            "provider": "anthropic" if index == 2 else "openai",
            "model": f"owner-model-{index}",
            "credential_ref": f"KNOT_BUNDLE_OWNER_{index}_KEY",
            "base_url": "",
        }
    return workflow


class OwnerBundleTests(unittest.TestCase):
    def test_export_preserves_owner_models_without_requiring_or_copying_keys(self):
        workflow = owner_workflow()
        values = {member["connection"]["credential_ref"]: f"fixture-member-private-value-{index}"
                  for index, member in enumerate(workflow["project"]["members"])}
        with patch.dict(os.environ, values):
            content = build_bundle(workflow, {"backend": "opencode"})
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(json.loads(archive.read("workflow.json")), workflow)
            execution = json.loads(archive.read("knot.json"))
            self.assertEqual(execution["backend"], "opencode")
            self.assertEqual(execution["model"], "")
            env = archive.read(".env.example").decode()
            for ref in values:
                self.assertIn(ref + "=\n", env)
            self.assertNotIn("OPENAI_API_KEY=", env)
            for info in archive.infolist():
                for value in values.values():
                    self.assertNotIn(value.encode(), archive.read(info.filename), info.filename)
            self.assertIn("runtime/owner_connections.py", archive.namelist())
            guidance = archive.read("AGENTS.md").decode()
            self.assertIn("each task owner's connection", guidance)
            self.assertNotIn("All roles use the selected local backend", guidance)
            start = archive.read("START-HERE.md").decode()
            self.assertIn("Copy `.env.example` to `.env`", start)
            self.assertIn("separate run", start)
            self.assertNotIn("Shared model:", start)
            for node in workflow["nodes"]:
                if node["type"] != "agent_task":
                    continue
                member = next(m for m in workflow["project"]["members"] if m["id"] == node["config"]["owner_id"])
                filename = next(n for n in archive.namelist() if n.startswith("tasks/") and n.endswith(f"-{node['id']}.md"))
                task = archive.read(filename).decode()
                self.assertIn(member["connection"]["model"], task)
                self.assertNotIn("Use the shared backend/model", task)
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(build_bundle(workflow, {"backend": "opencode"}))

    def test_missing_task_owner_connection_is_an_export_error(self):
        workflow = owner_workflow()
        owner = next(m for m in workflow["project"]["members"] if m["id"] == "member-1")
        owner.pop("connection")
        with self.assertRaises(BundleError) as raised:
            build_bundle(workflow, {"backend": "opencode"})
        self.assertTrue(raised.exception.issues)
        self.assertTrue(any(issue.get("node_id") for issue in raised.exception.issues))
        # The old shared CLI mode does not require member API credentials.
        self.assertTrue(build_bundle(workflow, {"backend": "codex"}))

    def test_review_only_member_does_not_need_a_model(self):
        workflow = owner_workflow()
        workflow["project"]["members"].append({"id": "review-only", "name": "Reviewer", "skills": ""})
        next(n for n in workflow["nodes"] if n["type"] == "human_review")["config"]["owner_id"] = "review-only"
        self.assertTrue(build_bundle(workflow, {"backend": "opencode"}))

    def test_member_credential_value_hidden_in_task_text_is_rejected(self):
        workflow = owner_workflow()
        ref = workflow["project"]["members"][0]["connection"]["credential_ref"]
        secret = "fixture-owner-value-with-no-standard-key-prefix"
        workflow["project"]["goal"] += " " + secret
        with patch.dict(os.environ, {ref: secret}):
            with self.assertRaises(BundleError):
                reject_secrets(workflow)
            with self.assertRaises(BundleError):
                build_bundle(workflow, {"backend": "opencode"})

    def test_exported_owner_resolver_runs_without_editor_files(self):
        workflow = owner_workflow()
        with temporary_run("owner-portable-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(build_bundle(workflow, {"backend": "opencode"}))) as archive:
                archive.extractall(root)
            script = ("import json; from runtime.owner_connections import resolve_owner_connection; "
                      "w=json.load(open('workflow.json',encoding='utf-8')); "
                      "n=next(n for n in w['nodes'] if n['id']=='research'); "
                      "r=resolve_owner_connection(w,n); print(r['model'])")
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            completed = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                                       text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "owner-model-1")


class OwnerWorkspaceTests(unittest.TestCase):
    def test_task_prompt_omits_every_members_connection_without_mutating_workflow(self):
        workflow = owner_workflow()
        original = deepcopy(workflow)
        node = next(n for n in workflow["nodes"] if n["id"] == "research")
        agent = next(a for a in workflow["agents"] if a["id"] == node["config"]["agent_id"])
        prompt = task_prompt(workflow, node, agent)
        assignment = json.loads(prompt.split("Assigned work:\n", 1)[1])
        self.assertEqual(assignment["project"]["goal"], workflow["project"]["goal"])
        for member in workflow["project"]["members"]:
            self.assertNotIn(member["connection"]["credential_ref"], prompt)
            self.assertNotIn(member["connection"]["model"], prompt)
        self.assertTrue(all(set(member) == {"id", "name", "skills"} for member in assignment["project"]["members"]))
        self.assertEqual(workflow, original)

    def test_private_runtime_config_is_excluded_but_project_opencode_files_survive(self):
        workflow = owner_workflow()
        with temporary_run("owner-handoff-") as directory:
            root = Path(directory)
            seed = root / "workspace"
            (seed / ".knot/opencode").mkdir(parents=True)
            (seed / ".knot/opencode/runtime.json").write_text('{"runtime":true}', encoding="utf-8")
            (seed / ".opencode/agents").mkdir(parents=True)
            (seed / ".opencode/agents/reviewer.md").write_text("Review code style.", encoding="utf-8")
            (seed / "opencode.jsonc").write_text('{"model":"project-model"}', encoding="utf-8")
            workspace = LocalWorkspace(root, workflow)
            workspace.initialize()
            self.assertEqual(set(workspace.seed), {".opencode/agents/reviewer.md", "opencode.jsonc"})


if __name__ == "__main__":
    unittest.main()
