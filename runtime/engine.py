"""Deterministic DAG orchestration, real concurrency and persisted human review."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .providers import ProviderError, complete
from .security import MAX_FILE_BYTES, redact, safe_path, register_secret
from .tools import ToolRunner, read_limited
from .validation import validate_workflow

TERMINAL = {"succeeded", "failed", "blocked", "skipped"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(workflow: dict) -> str:
    return hashlib.sha256(json.dumps(workflow, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def serialize_output(result: dict, file_format: str) -> str:
    data = result.get("data")
    if file_format == "markdown":
        return str(result.get("content", "")) + "\n"
    if file_format == "json":
        return json.dumps(data if data is not None else result, ensure_ascii=False, indent=2) + "\n"
    if file_format != "csv":
        raise ValueError("Unsupported output format")
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    if isinstance(data, list) and all(isinstance(row, dict) for row in data):
        columns = list(dict.fromkeys(str(key) for row in data for key in row))
        if not columns:
            raise ValueError("CSV output requires at least one named column")
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in data:
            normalized = {}
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    value = "'" + value
                normalized[str(key)] = value
            writer.writerow(normalized)
        return stream.getvalue()
    content = result.get("content", "")
    if isinstance(content, str) and "\n" in content and "," in content.splitlines()[0]:
        return content.rstrip() + "\n"
    raise ValueError("CSV delivery needs data as a list of objects, data.rows, or CSV text")


class WorkflowError(ValueError):
    def __init__(self, issues: list[dict]):
        self.issues = issues
        super().__init__("; ".join(item["message"] for item in issues if item["severity"] == "error"))


class Engine:
    """The local machine is the trust boundary; members are attribution, not login."""

    def __init__(self, workflow: dict, root: Path | str, mode: str = "mock", state_path: Path | str | None = None):
        self.workflow = copy.deepcopy(workflow)
        import os
        for agent in workflow.get("agents", []) if isinstance(workflow, dict) else []:
            if isinstance(agent, dict) and isinstance(agent.get("credential_ref"), str):
                register_secret(os.environ.get(agent["credential_ref"], ""))
        issues = validate_workflow(workflow, mode)
        if any(item["severity"] == "error" for item in issues):
            raise WorkflowError(issues)
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.nodes = {node["id"]: node for node in workflow["nodes"]}
        self.agents = {agent["id"]: agent for agent in workflow["agents"]}
        self.resources = {resource["id"]: resource for resource in workflow["resources"]}
        self.incoming = {nid: [edge for edge in workflow["edges"] if edge["target"] == nid] for nid in self.nodes}
        self.limits = workflow["limits"]
        self.state_path = safe_path(self.root, str(state_path or "logs/run-state.json").replace("\\", "/"), ("logs",))
        self.log_path = safe_path(self.root, "logs/events.jsonl", ("logs",))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.resuming = False
        self.protected_outputs = {"results/" + mapping["filename"].replace("\\", "/") for node in workflow["nodes"] if node["type"] == "output" for mapping in node["config"]["mappings"]}
        self.state = {"schema_version": "1.0", "run_id": uuid.uuid4().hex, "workflow_hash": fingerprint(workflow), "mode": mode,
                      "status": "pending", "started_at": now(), "updated_at": now(),
                      "nodes": {nid: {"status": "pending", "attempts": 0} for nid in self.nodes}, "results": {}, "events": [], "warnings": [i for i in issues if i["severity"] == "warning"]}

    def _save(self) -> None:
        with self.lock:
            self.state["updated_at"] = now()
            temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            # This directory was checked by safe_path; recheck before each write.
            safe_path(self.root, self.state_path.relative_to(self.root).as_posix(), ("logs",))
            if temp.is_symlink():
                raise PermissionError("State temporary path cannot be a symlink")
            temp.write_text(json.dumps(redact(self.state), ensure_ascii=False, indent=2), encoding="utf-8")
            for attempt in range(5):
                try:
                    temp.replace(self.state_path)
                    break
                except PermissionError:
                    # Windows indexers/virus scanners can briefly hold a new
                    # state file open. Keep atomic replacement and retry briefly.
                    if attempt == 4:
                        raise
                    time.sleep(0.02 * (2 ** attempt))

    def _event(self, event: str, node_id: str | None = None, **details) -> None:
        with self.lock:
            record = redact({"time": now(), "event": event, **({"node_id": node_id} if node_id else {}), **details})
            self.state["events"].append(record)
            safe_path(self.root, "logs/events.jsonl", ("logs",))
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _preflight_inputs(self) -> None:
        used = {rid for node in self.nodes.values() if node["type"] == "shared_resource" for rid in node["config"]["resource_ids"]}
        for rid in used:
            resource = self.resources[rid]
            path = safe_path(self.root, resource["path"], ("inputs",))
            read_limited(path)

    def resume(self, review_id: str, decision: str, reviewer_id: str) -> "Engine":
        if decision not in ("approve", "reject"):
            raise ValueError("Explicit decision must be approve or reject")
        if not self.state_path.is_file():
            raise FileNotFoundError("No saved run exists to resume")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("workflow_hash") != fingerprint(self.workflow):
            raise ValueError("Workflow changed since this run. Export/run a new package instead of reusing its review state.")
        if state.get("mode") != self.mode:
            raise ValueError("Cannot resume a run in a different mode")
        if state.get("status") != "waiting_review":
            raise ValueError("Saved run is not waiting for human review")
        if set(state.get("nodes", {})) != set(self.nodes):
            raise ValueError("Saved run node set is invalid")
        if review_id not in self.nodes or self.nodes[review_id]["type"] != "human_review" or state["nodes"][review_id].get("status") != "waiting_review":
            raise ValueError("This node is not waiting for review")
        if reviewer_id != self.nodes[review_id]["config"]["owner_id"]:
            raise PermissionError("Reviewer id must match the configured owner; this records local approval, not remote identity verification")
        self.state = state
        self.resuming = True
        review = self.state["nodes"][review_id]
        review.update({"status": "succeeded" if decision == "approve" else "failed", "finished_at": now(), "reviewer_id": reviewer_id, "decision": decision})
        self.state["results"][review_id] = {"content": f"Human review {decision}", "data": {"approved": decision == "approve", "reviewer_id": reviewer_id}}
        if decision == "reject":
            review["error"] = "Human reviewer rejected this result"
        self._event("review_" + decision, review_id, reviewer_id=reviewer_id)
        self.state["status"] = "running"
        self._save()
        return self

    def _active(self, edge: dict) -> bool:
        source = edge["source"]
        if self.state["nodes"][source]["status"] != "succeeded":
            return False
        if edge["kind"] == "control" and self.nodes[source]["type"] == "condition":
            return edge["source_port"] == self.state["results"][source]["selected_port"]
        return True

    def _readiness(self, nid: str) -> str:
        edges = self.incoming[nid]
        statuses = [self.state["nodes"][edge["source"]]["status"] for edge in edges]
        if any(status in ("failed", "blocked") for status in statuses):
            return "blocked"
        if any(status not in TERMINAL for status in statuses):
            return "wait"
        controls = [edge for edge in edges if edge["kind"] == "control"]
        if controls:
            active = [self._active(edge) for edge in controls]
            if not any(active) or (self.nodes[nid]["config"].get("join_rule", "all_selected") == "all_success" and not all(active)):
                return "skipped"
        return "ready"

    def _inputs(self, nid: str) -> dict:
        return {edge["source"]: copy.deepcopy(self.state["results"][edge["source"]]) for edge in self.incoming[nid] if edge["kind"] == "data" and self.state["nodes"][edge["source"]]["status"] == "succeeded"}

    def _task(self, node: dict, inputs: dict, deadline: float) -> dict:
        cfg = node["config"]
        if self.mode == "mock":
            delay = cfg.get("mock_delay_ms", 100) / 1000
            remaining = deadline - time.monotonic()
            time.sleep(max(0, min(delay, remaining)))
            if time.monotonic() >= deadline:
                raise TimeoutError("Mock task exceeded its configured deadline")
            example = cfg.get("mock_result")
            if example is not None:
                if not isinstance(example, dict) or not isinstance(example.get("content"), str):
                    raise ValueError("mock_result must contain text content and optional data")
                result = copy.deepcopy(example)
            else:
                result = {"content": f"# {node['label']}\n\nMOCK EXAMPLE — no model was called.\n\nTask: {cfg['instructions']}\n\nExplicit inputs: {', '.join(inputs) or 'none'}\n\nAcceptance: {cfg['acceptance']}",
                          "data": {"mock": True, "task": node["label"], "input_nodes": list(inputs), "approved": True}}
                if cfg["output_format"] == "csv":
                    result["data"] = [{"task": node["label"], "mode": "mock", "input_count": len(inputs)}]
            result["mode"] = "mock"
            result.pop("usage", None)
            result["input_nodes"] = list(inputs)
            return redact(result)
        agent = self.agents[cfg["agent_id"]]
        runner = ToolRunner(self.root, agent, cfg, self.protected_outputs)

        def execute_tool(name: str, arguments: dict) -> Any:
            if time.monotonic() >= deadline:
                raise TimeoutError("Task deadline exceeded before tool execution")
            result = runner(name, arguments)
            self._event("tool_executed", node["id"], tool=name)
            return result

        prompt = json.dumps({"project_goal": self.workflow["project"]["goal"], "deliverable": self.workflow["project"]["deliverable"],
                             "task": node["label"], "instructions": cfg["instructions"], "acceptance": cfg["acceptance"],
                             "output_format": cfg["output_format"], "explicit_inputs": inputs,
                             "output_contract": "Return only a JSON object with content (Markdown or CSV text) and data (structured JSON; use a list of row objects for CSV). Do not invent sources or credentials. Acceptance is descriptive and must also be checked by the human reviewer."}, ensure_ascii=False)
        reply = complete(agent, agent["system_prompt"], prompt, runner.definitions, execute_tool,
                         timeout=max(0.01, deadline - time.monotonic()), max_tool_rounds=self.limits["max_tool_rounds"])
        decoded = reply.get("data")
        if isinstance(decoded, dict) and isinstance(decoded.get("content"), str) and "data" in decoded:
            result = {"content": decoded["content"], "data": decoded["data"]}
        else:
            result = {"content": reply["content"], "data": decoded}
        if cfg["output_format"] == "json" and result["data"] is None:
            raise ValueError("Task requested JSON but the provider did not return valid structured JSON")
        if cfg["output_format"] == "csv":
            serialize_output(result, "csv")
        if reply.get("usage"):
            result["usage"] = reply["usage"]
        result.update({"mode": "real", "input_nodes": list(inputs)})
        return redact(result)

    def _execute(self, node: dict, inputs: dict, deadline: float) -> dict:
        kind, cfg = node["type"], node["config"]
        if kind == "start":
            return {"content": self.workflow["project"]["goal"], "data": {"project": self.workflow["project"]}}
        if kind == "parallel":
            return {"content": "Parallel branches activated", "data": {"branch": True}}
        if kind == "shared_resource":
            contents = []
            for rid in cfg["resource_ids"]:
                resource = self.resources[rid]
                contents.append({"id": rid, "name": resource["name"], "path": resource["path"], "example": resource["example"], "content": read_limited(safe_path(self.root, resource["path"], ("inputs",)))})
            return redact({"content": "\n\n".join(item["content"] for item in contents), "data": {"resources": contents}})
        if kind == "agent_task":
            return self._task(node, inputs, deadline)
        if kind == "condition":
            if cfg["source_node"] not in inputs:
                raise ValueError("Condition's selected data source was skipped or unavailable")
            value = inputs[cfg["source_node"]]
            for key in cfg["field"].split("."):
                if isinstance(value, dict) and key in value:
                    value = value[key]
                elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    raise ValueError(f"Condition field is missing: {cfg['field']}")
            expected = cfg["value"]
            operation = cfg["operator"]
            if operation == "eq":
                matched = type(value) is type(expected) and value == expected
            elif operation == "neq":
                matched = type(value) is not type(expected) or value != expected
            elif operation == "gt":
                if type(value) not in (int, float) or type(expected) not in (int, float):
                    raise ValueError("gt condition needs numeric values")
                matched = value > expected
            else:
                if not isinstance(value, (str, list, dict)):
                    raise ValueError("contains condition needs text, array or object")
                matched = expected in value
            return {"content": f"Condition is {'true' if matched else 'false'}", "data": {"matched": bool(matched)}, "selected_port": "true" if matched else "false"}
        if kind == "output":
            prepared = []
            for mapping in cfg["mappings"]:
                source = mapping["source_node"]
                if source not in inputs:
                    raise ValueError(f"Output data source {source} was skipped or unavailable; change the mapping or branch")
                path = safe_path(self.root, "results/" + mapping["filename"], ("results",))
                content = redact(serialize_output(inputs[source], mapping["format"]))
                if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                    raise ValueError("Output exceeds the 2 MB file limit")
                prepared.append((path, content))
            for path, content in prepared:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            return {"content": "Final files saved", "data": {"files": [path.relative_to(self.root).as_posix() for path, _ in prepared]}}
        raise ValueError(f"Unsupported node execution type: {kind}")

    def _with_retries(self, node: dict, inputs: dict) -> dict:
        for attempt in range(self.limits["max_retries"] + 1):
            with self.lock:
                self.state["nodes"][node["id"]]["attempts"] = attempt + 1
            deadline = time.monotonic() + self.limits["timeout_seconds"]
            try:
                result = self._execute(node, inputs, deadline)
                if time.monotonic() > deadline:
                    raise TimeoutError("Task exceeded its deadline")
                return redact(result)
            except (PermissionError, ValueError, FileNotFoundError):
                # Configuration/permission failures cannot be repaired by retrying.
                raise
            except Exception as error:
                if attempt >= self.limits["max_retries"]:
                    raise
                self._event("retry", node["id"], attempt=attempt + 1, error=redact(str(error)))
        raise RuntimeError("Retry limit exhausted")

    def run(self) -> dict:
        if not self.resuming and self.state_path.exists():
            raise ValueError("A run already exists in this directory. Resume its review, or use a new run directory.")
        self._preflight_inputs()
        self.state["status"] = "running"
        self._event("run_resumed" if self.resuming else "run_started", mode=self.mode)
        self._save()
        futures = {}
        with ThreadPoolExecutor(max_workers=self.limits["max_concurrency"], thread_name_prefix="teamblocks") as pool:
            while True:
                changed = False
                for nid, node in self.nodes.items():
                    status = self.state["nodes"][nid]
                    if status["status"] != "pending":
                        continue
                    ready = self._readiness(nid)
                    if ready in ("blocked", "skipped"):
                        status.update({"status": ready, "finished_at": now()})
                        if ready == "blocked":
                            status["error"] = "A dependency failed or was rejected"
                        self._event(ready, nid)
                        changed = True
                    elif ready == "ready":
                        if node["type"] == "human_review":
                            status.update({"status": "waiting_review", "started_at": now(), "owner_id": node["config"]["owner_id"], "instructions": node["config"]["instructions"], "input_nodes": list(self._inputs(nid))})
                            self._event("waiting_review", nid, owner_id=node["config"]["owner_id"])
                            changed = True
                        elif len(futures) < self.limits["max_concurrency"]:
                            status.update({"status": "running", "started_at": now()})
                            self._event("node_started", nid)
                            futures[pool.submit(self._with_retries, node, self._inputs(nid))] = nid
                            changed = True
                if changed:
                    self._save()
                if futures:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        nid = futures.pop(future)
                        status = self.state["nodes"][nid]
                        status["finished_at"] = now()
                        try:
                            self.state["results"][nid] = future.result()
                            status["status"] = "succeeded"
                            self._event("node_succeeded", nid)
                        except Exception as error:
                            status.update({"status": "failed", "error": redact(str(error)), "error_type": type(error).__name__})
                            self._event("node_failed", nid, error=status["error"], error_type=status["error_type"])
                    self._save()
                    continue
                if changed:
                    continue
                statuses = [item["status"] for item in self.state["nodes"].values()]
                if "waiting_review" in statuses:
                    self.state["status"] = "waiting_review"
                elif any(status in ("failed", "blocked") for status in statuses):
                    self.state["status"] = "failed"
                elif "pending" in statuses:
                    self.state["status"] = "failed"
                    for nid, status in self.state["nodes"].items():
                        if status["status"] == "pending":
                            status.update({"status": "blocked", "error": "No runnable dependencies remain"})
                            self._event("blocked", nid, error=status["error"])
                else:
                    self.state["status"] = "completed"
                self._event("run_" + self.state["status"])
                self._save()
                return copy.deepcopy(self.state)
