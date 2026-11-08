"""Authoritative schema + graph validation used by editor export and executor."""
from __future__ import annotations

import math
import os
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

from .security import ENV_RE, ID_RE, contains_secret, relative_path

NODE_TYPES = {"start", "agent_task", "shared_resource", "parallel", "condition", "human_review", "output"}
TOOLS = {"read_text", "read_csv", "summarize_csv", "write_file"}
FORMATS = {"markdown", "json", "csv"}


def validate_workflow(workflow: Any, mode: str = "mock") -> list[dict]:
    """Malformed imported JSON is a validation error, never an API crash."""
    try:
        return _validate_workflow(workflow, mode)
    except (TypeError, AttributeError, KeyError, ValueError, OverflowError):
        return [{"severity": "error", "code": "schema", "message": "Malformed workflow field type. IDs, ports and tool names must be strings; configs must be objects and collections must be arrays."}]


def _validate_workflow(workflow: Any, mode: str = "mock") -> list[dict]:
    issues: list[dict] = []

    def issue(code: str, message: str, node_id: str | None = None, severity: str = "error") -> None:
        entry = {"severity": severity, "code": code, "message": message}
        if node_id:
            entry["node_id"] = node_id
        issues.append(entry)

    def string(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def identifiers(items: Any, label: str) -> dict:
        if not isinstance(items, list):
            issue("schema", f"{label} must be an array")
            return {}
        found = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ID_RE.fullmatch(item["id"]):
                issue("schema", f"Every {label} entry needs a safe unique id")
                continue
            if item["id"] in found:
                issue("duplicate_id", f"Duplicate {label} id: {item['id']}")
            found[item["id"]] = item
        return found

    if not isinstance(workflow, dict):
        return [{"severity": "error", "code": "schema", "message": "Workflow must be a JSON object"}]
    if contains_secret(workflow):
        issue("secret", "Workflow contains a secret or credential literal. Use an environment-variable credential reference only.")
    if workflow.get("schema_version") != "1.0":
        issue("schema_version", "Only schema_version 1.0 is supported")
    if mode not in {"mock", "real", "local"}:
        issue("mode", "Mode must be mock, real or local")
    project = workflow.get("project")
    if not isinstance(project, dict):
        issue("schema", "project must be an object")
        project = {}
    for key in ("id", "name", "goal", "deliverable"):
        if not string(project.get(key)):
            issue("project", f"Project {key} is required")
    members = identifiers(project.get("members"), "members")
    if not members:
        issue("members", "At least one member is required")
    for member in members.values():
        if not string(member.get("name")) or not isinstance(member.get("skills", ""), str):
            issue("members", "Members need a name and text skills")
    agents = identifiers(workflow.get("agents"), "agents")
    nodes = identifiers(workflow.get("nodes"), "nodes")
    resources = identifiers(workflow.get("resources"), "resources")
    edges = identifiers(workflow.get("edges"), "edges")
    if not nodes:
        issue("empty_graph", "Add a Start node and build a workflow")
    limits = workflow.get("limits")
    if not isinstance(limits, dict):
        issue("limits", "Runtime limits are required")
        limits = {}
    bounds = {"max_concurrency": (1, 16), "timeout_seconds": (1, 3600), "max_retries": (0, 5), "max_tool_rounds": (1, 20)}
    for key, (low, high) in bounds.items():
        value = limits.get(key)
        if type(value) is not int or not low <= value <= high:
            issue("limits", f"{key} must be an integer from {low} to {high}")
    viewport = workflow.get("viewport")
    if not isinstance(viewport, dict) or any(type(viewport.get(k)) not in (int, float) or not math.isfinite(viewport[k]) for k in ("x", "y", "zoom")) or viewport.get("zoom", 0) <= 0:
        issue("schema", "viewport requires finite x, y and positive zoom")
    if not isinstance(workflow.get("design_notes"), list) or any(not isinstance(n, str) for n in workflow.get("design_notes", [])):
        issue("schema", "design_notes must be an array of strings")
    for aid, agent in agents.items():
        for key in ("name", "role", "system_prompt"):
            if not string(agent.get(key)):
                issue("agent_config", f"Agent {aid}: {key} is required")
        if agent.get("provider") not in ("openai", "anthropic"):
            issue("provider", f"Agent {aid}: unsupported provider")
        if mode != "local" and not string(agent.get("model")):
            issue("model", f"Agent {aid}: configure a model before real execution", severity="error" if mode == "real" else "warning")
        ref = agent.get("credential_ref", "")
        if not isinstance(ref, str) or not ENV_RE.fullmatch(ref):
            issue("credential_ref", f"Agent {aid}: use an uppercase environment-variable name for credential_ref")
        elif mode == "real" and not os.environ.get(ref):
            issue("credential_missing", f"Agent {aid}: environment credential {ref} is not configured")
        ts = agent.get("tools")
        if not isinstance(ts, list) or any(not isinstance(t, str) or t not in TOOLS for t in ts):
            issue("tools", f"Agent {aid}: tools must be a list of supported tool names")
        base = agent.get("base_url")
        if base:
            parsed = urlparse(base) if isinstance(base, str) else None
            if not parsed or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
                issue("base_url", f"Agent {aid}: base_url must use HTTPS (or loopback HTTP), without embedded credentials")
    resource_paths = set()
    for rid, resource in resources.items():
        try:
            path = relative_path(resource.get("path"), ("inputs",))
            if path.casefold() in resource_paths:
                issue("resource_path", f"Resource path is duplicated: {path}")
            resource_paths.add(path.casefold())
        except ValueError as error:
            issue("resource_path", f"Resource {rid}: {error}")
        if not string(resource.get("name")) or not isinstance(resource.get("description", ""), str) or not isinstance(resource.get("example"), bool):
            issue("schema", f"Resource {rid} needs name, description and example flag")
        if "content" in resource and not isinstance(resource["content"], str):
            issue("resource_content", f"Resource {rid}: inline content must be text")
        elif "content" not in resource:
            issue("missing_input", f"Provide resource {rid} at {resource.get('path', 'inputs/')} before running", severity="warning")
    controls = defaultdict(list)
    data_inputs = defaultdict(set)
    adjacency = defaultdict(set)
    signature = set()
    for eid, edge in edges.items():
        source, target, kind = edge.get("source"), edge.get("target"), edge.get("kind")
        if not isinstance(source, str) or not isinstance(target, str) or source not in nodes or target not in nodes:
            issue("edge_node", f"Edge {eid} refers to a missing node")
            continue
        if source == target:
            issue("cycle", "A node cannot connect to itself", target)
        if kind not in ("control", "data"):
            issue("edge_kind", f"Edge {eid} must be control or data", target)
            continue
        sig = (source, target, edge.get("source_port"), edge.get("target_port"), kind)
        if sig in signature:
            issue("duplicate_edge", f"Duplicate connection {eid}", target)
        signature.add(sig)
        adjacency[source].add(target)
        if nodes[target].get("type") == "start":
            issue("start_input", "Start cannot have incoming edges", target)
        if kind == "data":
            if edge.get("source_port") != "data-out" or edge.get("target_port") != "data-in":
                issue("ports", f"Data edge {eid} must connect data-out to data-in", target)
            data_inputs[target].add(source)
        else:
            controls[source].append(target)
            expected = {"true", "false"} if nodes[source].get("type") == "condition" else {"out"}
            if edge.get("source_port") not in expected or edge.get("target_port") != "in":
                issue("ports", f"Control edge {eid} has incompatible ports", target)
            if nodes[source].get("type") == "output":
                issue("output_edge", "Output is a final sink and has no outgoing control port", source)
    indegree = {nid: 0 for nid in nodes}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    queue = deque(nid for nid, count in indegree.items() if count == 0)
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        issue("cycle", "Workflow contains a cycle in execution or data dependencies")
    starts = [nid for nid, node in nodes.items() if node.get("type") == "start"]
    if len(starts) != 1:
        issue("start_count", "Workflow must contain exactly one Start")
    else:
        reachable = {starts[0]}
        queue = deque(starts)
        while queue:
            for target in controls[queue.popleft()]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        for nid in nodes.keys() - reachable:
            issue("unreachable", "Connect this node to Start with execution connections", nid)
    output_paths = set()
    if not any(n.get("type") == "output" for n in nodes.values()):
        issue("output_missing", "Add an Output node to deliver the result")
    for nid, node in nodes.items():
        kind = node.get("type")
        if kind not in NODE_TYPES:
            issue("node_type", "Unsupported block type", nid)
        if not string(node.get("label")):
            issue("node_label", "Block needs a name", nid)
        position = node.get("position")
        if not isinstance(position, dict) or any(type(position.get(k)) not in (int, float) or not math.isfinite(position[k]) for k in ("x", "y")):
            issue("schema", "Block position requires finite x and y", nid)
        cfg = node.get("config")
        if not isinstance(cfg, dict):
            issue("schema", "Block config must be an object", nid)
            continue
        if cfg.get("join_rule", "all_selected") not in ("all_selected", "all_success"):
            issue("join_rule", "Unknown join rule", nid)
        if kind in ("agent_task", "human_review") and cfg.get("owner_id") not in members:
            issue("owner", "Assign an existing human owner", nid)
        if kind == "agent_task":
            aid = cfg.get("agent_id")
            if aid not in agents:
                issue("agent_missing", "Choose a configured agent", nid)
            if not string(cfg.get("instructions")):
                issue("instructions", "Task instructions are required", nid)
            if not string(cfg.get("acceptance")):
                issue("acceptance", "Task acceptance requirements are required", nid)
            if cfg.get("output_format") not in FORMATS:
                issue("output_format", "Choose markdown, json or csv output", nid)
            requested = cfg.get("tools", [])
            if not isinstance(requested, list) or any(not isinstance(t, str) or t not in TOOLS for t in requested):
                issue("tools", "Task includes unsupported tools", nid)
            elif aid in agents and any(t not in agents[aid].get("tools", []) for t in requested):
                issue("tool_permission", "Task tools exceed this agent's allowed tools", nid)
            permissions = cfg.get("permissions")
            if not isinstance(permissions, dict):
                issue("permissions", "Explicit read/write permission lists are required", nid)
            else:
                for action in ("read", "write"):
                    values = permissions.get(action)
                    if not isinstance(values, list):
                        issue("permissions", f"{action} permissions must be an array", nid)
                        continue
                    for value in values:
                        try:
                            relative_path(value.rstrip("/") if isinstance(value, str) else value, ("results",) if action == "write" else ("inputs", "results"))
                        except ValueError as error:
                            issue("permissions", str(error), nid)
            if "mock_delay_ms" in cfg and (type(cfg["mock_delay_ms"]) not in (int, float) or not 0 <= cfg["mock_delay_ms"] <= 10000):
                issue("mock_delay", "Mock delay must be 0–10000 milliseconds", nid)
        elif kind == "shared_resource":
            ids = cfg.get("resource_ids")
            if not isinstance(ids, list) or not ids:
                issue("resource_missing", "Choose at least one shared resource", nid)
            elif any(rid not in resources for rid in ids):
                issue("resource_missing", "Shared Resource refers to an unknown resource", nid)
        elif kind == "condition":
            if cfg.get("source_node") not in data_inputs[nid]:
                issue("condition_input", "Condition source needs an explicit incoming data connection", nid)
            if not string(cfg.get("field")) or cfg.get("operator") not in ("eq", "neq", "gt", "contains") or "value" not in cfg:
                issue("condition", "Configure condition field, supported operator and comparison value", nid)
            ports = {edge.get("source_port") for edge in edges.values() if edge.get("source") == nid and edge.get("kind") == "control"}
            if ports != {"true", "false"}:
                issue("condition_branches", "Condition needs both true and false branches", nid)
        elif kind == "human_review":
            if not string(cfg.get("instructions")):
                issue("review_instructions", "Describe what the owner must review", nid)
        elif kind == "output":
            mappings = cfg.get("mappings")
            if not isinstance(mappings, list) or not mappings:
                issue("output_mapping", "Configure at least one output file", nid)
                continue
            for mapping in mappings:
                if not isinstance(mapping, dict):
                    issue("output_mapping", "Output mappings must be objects", nid)
                    continue
                if mapping.get("source_node") not in data_inputs[nid]:
                    issue("output_input", "Each output source needs an explicit incoming data connection", nid)
                if mapping.get("format") not in FORMATS:
                    issue("output_format", "Unsupported output file format", nid)
                try:
                    path = relative_path(mapping.get("filename"))
                    if mode == "local" and (path.casefold() == "project" or path.casefold().startswith("project/") or path.casefold().startswith("task-")):
                        issue("output_path", "Local coding reserves results/project/ and results/task-*/ for delivered source files. Choose a different report filename.", nid)
                    if path.casefold() in output_paths:
                        issue("output_collision", f"More than one output writes {path}", nid)
                    output_paths.add(path.casefold())
                except ValueError as error:
                    issue("output_path", str(error), nid)
    return issues
