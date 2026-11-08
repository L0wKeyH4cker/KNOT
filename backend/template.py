"""A clearly labelled, deterministic teaching template; never an AI response."""
from copy import deepcopy
import json
from pathlib import Path


def load_template():
    return json.loads((Path(__file__).resolve().parents[1] / "examples" / "team-research.json").read_text(encoding="utf-8"))


def template_for_project(project=None):
    workflow = deepcopy(load_template())
    if project:
        workflow["project"] = project
        members = project.get("members", [])
        if members:
            tasks = [n for n in workflow["nodes"] if n["type"] in ("agent_task", "human_review")]
            for index, node in enumerate(tasks):
                node["config"]["owner_id"] = members[index % len(members)]["id"]
    return workflow
