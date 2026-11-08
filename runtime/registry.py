"""Local discovery of KNOT runs without scanning the user's filesystem.

Each launcher owns one small registration file. Observers read only explicitly
registered run state or a directory the user supplies. A stale heartbeat means
disconnected, not completed; monitoring never sends signals to a runner.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
from typing import Any
import uuid

from .activity import sanitize_text
from .security import resolve_path, safe_path

HEARTBEAT_SECONDS = 2.0
STALE_SECONDS = 12.0
MAX_ENTRY_BYTES = 16_384
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_WORKFLOW_BYTES = 8 * 1024 * 1024
MAX_REGISTRATIONS = 1000
MAX_NODES = 1000
MAX_EVENTS = 30
_STATUSES = {"pending", "running", "waiting_review", "succeeded", "completed", "failed", "blocked", "skipped", "cancelled", "interrupted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_registry_dir() -> Path:
    override = os.environ.get("KNOT_RUNS_DIR")
    if override:
        return Path(override).expanduser().absolute()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "KNOT" / "runs"
    base = Path(os.environ["XDG_STATE_HOME"]) if os.environ.get("XDG_STATE_HOME") else Path.home() / ".local" / "state"
    return base / "knot" / "runs"


def _seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _regular_json(path: Path, limit: int) -> dict | None:
    """Ignore incomplete, oversized, linked or non-JSON registration/state files."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > limit:
            return None
        with path.open("r", encoding="utf-8-sig") as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            return None
        value = json.loads(content)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def _state_path(root: Path, state_path: Path | str) -> Path:
    path = Path(state_path)
    if path.is_absolute():
        # Do not resolve the candidate before safe_path checks its symlinks.
        relative = path.relative_to(root).as_posix()
    else:
        relative = path.as_posix()
    return safe_path(root, relative, ("logs",))


class RunRegistration:
    """A best-effort launcher heartbeat. Registration failure never stops work."""

    def __init__(self, root: Path | str, state_path: Path | str, run_id: str,
                 registry_dir: Path | str | None = None, *, heartbeat_interval: float = HEARTBEAT_SECONDS):
        self.root = resolve_path(root)
        self.state_path = _state_path(self.root, state_path)
        self.run_id = str(run_id)
        self.registry_dir = Path(registry_dir) if registry_dir is not None else default_registry_dir()
        self.registry_dir = self.registry_dir.expanduser().absolute()
        key = json.dumps([os.path.normcase(str(self.root)), os.path.normcase(str(self.state_path)), self.run_id], ensure_ascii=False).encode("utf-8")
        self.filename = hashlib.sha256(key).hexdigest() + ".json"
        self.interval = max(0.05, min(float(heartbeat_interval), STALE_SECONDS / 2))
        self.warnings: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._started = False
        self._closed = False

    @property
    def warning(self) -> str | None:
        return self.warnings[0] if self.warnings else None

    def _warn(self, error: Exception) -> None:
        if not self.warnings:
            self.warnings.append(f"Local run discovery is unavailable ({type(error).__name__}). You can still monitor this run by supplying its directory.")

    def _write(self, active: bool) -> None:
        temporary: Path | None = None
        try:
            self.registry_dir.mkdir(parents=True, exist_ok=True)
            if self.registry_dir.is_symlink() or getattr(self.registry_dir.lstat(), "st_file_attributes", 0) & 0x400:
                raise PermissionError("Registration directory cannot be a link")
            destination = safe_path(self.registry_dir, self.filename, (self.filename,))
            temporary_name = self.filename + "." + uuid.uuid4().hex + ".tmp"
            temporary = safe_path(self.registry_dir, temporary_name, (temporary_name,))
            record = {"schema_version": "1.0", "run_id": self.run_id,
                      "root": str(self.root), "state_path": str(self.state_path),
                      "pid": os.getpid(), "heartbeat_at": _now(), "active": active}
            payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
            if len(payload.encode("utf-8")) > MAX_ENTRY_BYTES:
                raise ValueError("Registration metadata is too large")
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            if os.name != "nt":
                temporary.chmod(0o600)
            for attempt in range(4):
                try:
                    safe_path(self.registry_dir, self.filename, (self.filename,))
                    temporary.replace(destination)
                    temporary = None
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.025 * (2 ** attempt))
        except (OSError, ValueError) as error:
            self._warn(error)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                if not self._closed:
                    self._write(True)

    def start(self) -> "RunRegistration":
        with self._lock:
            if self._closed or self._started:
                return self
            self._started = True
            self._write(True)
            self._thread = threading.Thread(target=self._heartbeat, name="knot-heartbeat", daemon=True)
            self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._started:
                self._write(False)

    def __enter__(self) -> "RunRegistration":
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _text(value: Any, limit: int = 300) -> str:
    return sanitize_text(value if isinstance(value, str) else "", limit=limit)


def _activity(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    result = {key: _text(value.get(key), 500 if key == "text" else 80)
              for key in ("kind", "text", "status", "tool") if isinstance(value.get(key), str)}
    if isinstance(value.get("paths"), list):
        result["paths"] = [_text(p, 300) for p in value["paths"][:10] if isinstance(p, str)]
    if type(value.get("exit_code")) is int:
        result["exit_code"] = value["exit_code"]
    return result or None


def _event(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    event = {key: _text(value.get(key), 500 if key in {"text", "error"} else 160)
             for key in ("time", "node_id", "label", "event", "text", "error") if isinstance(value.get(key), str)}
    activity = _activity(value.get("activity"))
    detail = value.get("detail")
    if activity is None and isinstance(detail, dict):
        activity = _activity(detail.get("activity"))
        if activity is None and detail.get("item_type"):
            activity = {"kind": "status", "text": _text(detail.get("item_type"), 120)}
    if activity:
        event["activity"] = activity
        event["text"] = activity.get("text", event.get("text", ""))
    return event or None


def _snapshot(root: Path, state_path: Path, registration: dict | None, now: float) -> dict | None:
    progress_path = _state_path(root, state_path.with_name(state_path.stem + ".progress.json"))
    state = _regular_json(progress_path, MAX_STATE_BYTES)
    if state is not None:
        try:
            # Explicit legacy roots have no registration ID to match. A newer
            # full state can indicate a replaced run, so don't show an old summary.
            if (registration and state.get("run_id") != registration.get("run_id")) or progress_path.stat().st_mtime_ns < state_path.stat().st_mtime_ns:
                state = None
        except OSError:
            state = None
    if state is None:
        state = _regular_json(state_path, MAX_STATE_BYTES)
    if not state or not isinstance(state.get("run_id"), str) or not isinstance(state.get("nodes"), dict):
        return None
    if registration is not None and registration.get("run_id") != state["run_id"]:
        return None  # Old registration for a folder that was reused for a new run.
    needs_workflow = not isinstance(state.get("project"), dict) or any(
        isinstance(item, dict) and (not item.get("label") or not item.get("type"))
        for item in state["nodes"].values()
    )
    workflow = (_regular_json(safe_path(root, "workflow.json", ("workflow.json",)), MAX_WORKFLOW_BYTES) or {}) if needs_workflow else {}
    raw_nodes = workflow.get("nodes", [])
    definitions = {n["id"]: n for n in raw_nodes[:MAX_NODES] if isinstance(n, dict) and isinstance(n.get("id"), str)} if isinstance(raw_nodes, list) else {}
    agents = workflow.get("agents", [])
    agent_names = {a["id"]: a.get("name", a["id"]) for a in agents[:MAX_NODES] if isinstance(a, dict) and isinstance(a.get("id"), str)} if isinstance(agents, list) else {}
    project = state.get("project") if isinstance(state.get("project"), dict) else workflow.get("project", {})
    if not isinstance(project, dict):
        project = {}
    nodes = {}
    for nid, item in list(state["nodes"].items())[:MAX_NODES]:
        if not isinstance(nid, str) or not isinstance(item, dict):
            continue
        definition = definitions.get(nid, {})
        config = definition.get("config", {})
        if not isinstance(config, dict):
            config = {}
        safe_id = _text(nid, 160)
        node = {"id": safe_id, "label": _text(item.get("label") or definition.get("label") or nid, 240),
                "type": _text(item.get("type") or definition.get("type"), 60),
                "agent_name": _text(item.get("agent_name") or agent_names.get(config.get("agent_id"), ""), 160),
                "status": item.get("status") if item.get("status") in _STATUSES else "unknown"}
        for key in ("started_at", "finished_at", "last_activity_at", "error", "instructions", "owner_id"):
            if isinstance(item.get(key), str):
                node[key] = _text(item[key], 600 if key in {"error", "instructions"} else 160)
        if isinstance(item.get("input_nodes"), list):
            node["input_nodes"] = [_text(n, 160) for n in item["input_nodes"][:MAX_NODES] if isinstance(n, str)]
        activity = _activity(item.get("activity"))
        if activity:
            node["activity"] = activity
        nodes[safe_id] = node
    heartbeat = registration.get("heartbeat_at") if registration else None
    stamp = _seconds(heartbeat)
    age = max(0.0, now - stamp) if stamp is not None else None
    live = bool(registration and registration.get("active") is True and age is not None and age <= STALE_SECONDS and stamp <= now + STALE_SECONDS)
    status = state.get("status") if state.get("status") in _STATUSES else "unknown"
    raw_events = state.get("last_events", state.get("events", []))
    events = [safe for value in raw_events[-MAX_EVENTS:] if (safe := _event(value))] if isinstance(raw_events, list) else []
    execution = state.get("execution", {})
    if not isinstance(execution, dict):
        execution = {}
    return {"run_id": _text(state["run_id"], 160), "root": str(root), "state_path": str(state_path),
            "project": {"id": _text(project.get("id"), 160), "name": _text(project.get("name") or root.name, 240)},
            "mode": _text(state.get("mode"), 40),
            "execution": {"backend": _text(execution.get("backend"), 60), "model": _text(execution.get("model"), 200)},
            "status": status, "display_status": "disconnected" if status == "running" and not live else status,
            "started_at": _text(state.get("started_at"), 100), "updated_at": _text(state.get("updated_at"), 100),
            "nodes": nodes, "last_events": events,
            "heartbeat_at": _text(heartbeat, 100) if isinstance(heartbeat, str) else heartbeat,
            "heartbeat_age_seconds": age, "live": live}


def list_runs(registry_dir: Path | str | None = None, roots: list[Path | str] | None = None) -> list[dict]:
    """Return display-safe snapshots of registered runs and explicit directories."""
    directory = Path(registry_dir) if registry_dir is not None else default_registry_dir()
    found: dict[tuple[str, str], dict] = {}
    now = time.time()
    try:
        entries = sorted(directory.glob("*.json"))[:MAX_REGISTRATIONS]
    except OSError:
        entries = []
    for path in entries:
        record = _regular_json(path, MAX_ENTRY_BYTES)
        if not record or record.get("schema_version") != "1.0":
            continue
        try:
            raw_root, raw_state = record.get("root"), record.get("state_path")
            if not isinstance(raw_root, str) or not isinstance(raw_state, str) or not Path(raw_root).is_absolute():
                continue
            root = resolve_path(raw_root)
            state_path = _state_path(root, raw_state)
            snapshot = _snapshot(root, state_path, record, now)
            if snapshot:
                key = (os.path.normcase(str(root)), snapshot["run_id"])
                prior = found.get(key)
                if prior is None or (snapshot.get("heartbeat_at") or "") > (prior.get("heartbeat_at") or ""):
                    found[key] = snapshot
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    for value in (roots or [])[:MAX_REGISTRATIONS]:
        try:
            root = resolve_path(value)
            state_path = _state_path(root, "logs/run-state.json")
            snapshot = _snapshot(root, state_path, None, now)
            if snapshot:
                found.setdefault((os.path.normcase(str(root)), snapshot["run_id"]), snapshot)
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    return sorted(found.values(), key=lambda item: (item.get("started_at", ""), item["root"], item["run_id"]), reverse=True)
