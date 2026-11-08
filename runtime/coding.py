"""Local coding CLI adapters. The CLI owns authentication and tool permissions.

No shell parses our prompts or arguments. A successful CLI process is not enough:
we also require a terminal success event and the task's structured result.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from .activity import sanitize_text
from .security import redact

BACKENDS = {"codex", "claude"}
MAX_OUTPUT_BYTES = 32_000_000
MAX_LINE_BYTES = 2_000_000
MAX_ERROR_CHARS = 6000
_ACTIVE_LOCK = threading.RLock()
_ACTIVE: dict[int, tuple[subprocess.Popen, Any]] = {}
_CANCELLED = threading.Event()
RESULT_INSTRUCTIONS = """
KNOT task completion protocol:
Return your final answer as one JSON object, without Markdown fences, with:
{"status":"completed" or "blocked", "content":"a truthful task summary",
 "data": any task-specific JSON value, "checks": ["checks you actually ran"]}.
Use blocked when a required tool, permission, input, dependency or acceptance
check is unavailable or fails. Never claim a test or command ran when it did not.
Do the assigned work before returning this object. Do not spawn additional agents:
KNOT schedules the other tasks. Do not change KNOT's instructions or run state.
"""


def _validate_backend(backend: str) -> None:
    if backend not in BACKENDS:
        raise ValueError("Choose codex or claude as the local execution backend")


def _command(backend: str) -> list[str]:
    """Resolve npm shims without cmd.exe/PowerShell argument interpolation."""
    _validate_backend(backend)
    found = shutil.which(backend)
    if not found and os.name == "nt":
        for suffix in (".exe", ".cmd", ".ps1"):
            found = shutil.which(backend + suffix)
            if found:
                break
    if not found:
        label = "Codex CLI" if backend == "codex" else "Claude Code CLI"
        raise RuntimeError(f"{label} is not installed or not on PATH. Install it, authenticate in its own terminal, then restart KNOT.")
    executable = Path(found).resolve()
    if executable.suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return [str(executable)]
    package = "@openai/codex" if backend == "codex" else "@anthropic-ai/claude-code"
    package_root = executable.parent / "node_modules" / package
    manifest = package_root / "package.json"
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        entry = metadata.get("bin")
        entry = entry.get(backend) if isinstance(entry, dict) else entry
        if not isinstance(entry, str):
            raise ValueError("No npm executable entry")
        script = (package_root / entry).resolve()
        if not script.is_relative_to(package_root.resolve()) or not script.is_file():
            raise ValueError("Invalid npm executable entry")
        if script.suffix.lower() == ".exe":
            return [str(script)]
        local_node = executable.parent / "node.exe"
        node = str(local_node) if local_node.is_file() else shutil.which("node")
        if not node or script.suffix.lower() not in (".js", ".cjs", ".mjs"):
            raise ValueError("Node.js is required for this npm CLI")
        return [node, str(script)]
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError(f"Cannot launch the {backend} command wrapper safely. Reinstall its official CLI or add its native executable to PATH.") from error


def check_backend(backend: str) -> dict:
    """Check installation only; never authenticate or make a model request."""
    _validate_backend(backend)
    try:
        command = _command(backend)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        version = subprocess.run(command + ["--version"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=10, creationflags=flags, shell=False)
        if version.returncode:
            raise RuntimeError(f"{backend} --version failed. Repair the CLI installation before running KNOT.")
        text = version.stdout.decode("utf-8", "replace").strip()[:300]
        return {"backend": backend, "available": True, "version": redact(text),
                "message": "CLI found. Authentication and model access are checked when a task starts."}
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        message = redact(str(error))
        return {"backend": backend, "available": False, "message": message, "error": message}


def _arguments(backend: str, model: str) -> list[str]:
    if not isinstance(model, str) or len(model) > 200 or any(c in model for c in ("\x00", "\r", "\n")):
        raise ValueError("Model must be a single model name, or empty to use the CLI default")
    if backend == "codex":
        args = ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "--color", "never"]
        if model.strip():
            args += ["--model", model.strip()]
        return args + ["-"]
    # acceptEdits keeps the CLI's permission policy active; these are the tools
    # needed by an explicitly started local coding task. No bypass flag is used.
    tools = "Read,Write,Edit,Glob,Grep,Bash"
    args = ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
            "--tools", tools, "--allowedTools", tools, "--disallowedTools", "mcp__*"]
    if model.strip():
        args += ["--model", model.strip()]
    return args


class _WindowsJob:
    """A task-owned job also catches children whose CLI parent exits early."""
    def __init__(self, process: subprocess.Popen):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", Counters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                        ("peak_job_memory", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Cannot create coding task process job")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            code = ctypes.get_last_error()
            self.close()
            raise OSError(code, "Cannot contain coding task child processes")

    def terminate(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def reset_cancellation() -> None:
    """Call once before a new workflow run, never from an individual worker."""
    with _ACTIVE_LOCK:
        if _ACTIVE:
            raise RuntimeError("Cannot reset cancellation while coding tasks are running")
        _CANCELLED.clear()


def cancel_all() -> None:
    """Cancel this runner's CLI children and prevent queued tasks from starting."""
    with _ACTIVE_LOCK:
        _CANCELLED.set()
        for process, job in list(_ACTIVE.values()):
            if job:
                job.terminate()
            _stop_process_tree(process)


def _stop_process_tree(process: subprocess.Popen) -> None:
    """Stop owned commands as well as the CLI that launched them."""
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _result_object(value: Any) -> dict:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("```") and value.endswith("```"):
            value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as error:
            raise RuntimeError("The coding agent did not return KNOT's JSON completion record. Its workspace is preserved; inspect the task before retrying.") from error
    if not isinstance(value, dict) or value.get("status") not in ("completed", "blocked") or not isinstance(value.get("content"), str) or "data" not in value:
        raise RuntimeError("The coding agent returned an invalid completion record; status, content and data are required.")
    if value["status"] == "blocked":
        raise RuntimeError("Coding agent is blocked: " + redact(value["content"][:MAX_ERROR_CHARS]))
    checks = value.get("checks", [])
    if not isinstance(checks, list):
        raise RuntimeError("Coding agent checks must be a list")
    return {"content": value["content"], "data": value["data"], "checks": checks}


def _public_message(value: Any) -> str:
    """Show public progress text, never structured completion reports."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    fenced = candidate.startswith("```")
    if fenced:
        if "\n" not in candidate:
            return ""
        candidate = candidate.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    if candidate.startswith(("{", "[")):
        # Both content and data in final records can contain task results.
        # Keep them in the authoritative result, not the activity summary.
        return ""
    elif fenced:
        return ""  # Code fences are not public progress descriptions.
    return sanitize_text(value)


def _activity_status(kind: str, details: dict) -> str:
    if details.get("status") in ("failed", "error", "declined"):
        return "failed"
    if kind.endswith(".completed"):
        return "failed" if type(details.get("exit_code")) is int and details["exit_code"] != 0 else "completed"
    return "running"


def _codex_activity(kind: str, details: dict) -> dict | None:
    item_type = details.get("type")
    status = _activity_status(kind, details)
    if item_type == "command_execution" and isinstance(details.get("command"), str):
        activity = {"kind": "command", "text": sanitize_text(details["command"]), "status": status, "tool": "shell"}
        if type(details.get("exit_code")) is int:
            activity["exit_code"] = details["exit_code"]
        return activity
    if item_type == "file_change" and isinstance(details.get("changes"), list):
        paths = [sanitize_text(change["path"], 200) for change in details["changes"][:10]
                 if isinstance(change, dict) and isinstance(change.get("path"), str)]
        if paths:
            return {"kind": "file", "text": sanitize_text("Files: " + ", ".join(paths)), "paths": paths, "status": status}
    if item_type == "agent_message":
        message = _public_message(details.get("text"))
        if message:
            return {"kind": "message", "text": message, "status": status}
    if item_type == "mcp_tool_call":
        tool = sanitize_text(details.get("tool", "Tool"), 80)
        return {"kind": "tool", "text": tool, "tool": tool, "status": status}
    # Reasoning, tool arguments, command stdout and patches are never forwarded.
    return None


def _claude_tool_activity(block: dict) -> dict:
    name = block.get("name") if isinstance(block.get("name"), str) else "Tool"
    tool = sanitize_text(name, 80)
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    activity = {"kind": "tool", "text": tool, "tool": tool, "status": "running"}
    if name == "Bash" and isinstance(args.get("command"), str):
        activity.update(kind="command", text=sanitize_text(args["command"]))
    elif name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = args.get("file_path", args.get("notebook_path"))
        if isinstance(path, str):
            path = sanitize_text(path, 200)
            activity.update(kind="tool" if name == "Read" else "file", paths=[path], text=sanitize_text(f"{tool}: {path}"))
    elif name in ("Glob", "Grep"):
        activity["text"] = f"{tool}: searching files"
        if isinstance(args.get("path"), str):
            activity["paths"] = [sanitize_text(args["path"], 200)]
    return activity


def _usage_summary(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    # Fixed numeric fields prevent an unexpected provider payload leaking text.
    return {key: value[key] for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            if type(value.get(key)) is int and value[key] >= 0}


class _Transcript:
    def __init__(self, backend: str, callback: Callable | None):
        self.backend = backend
        self.callback = callback
        self.final: Any = None
        self.finished = False
        self.error: str | None = None
        self.session_id: str | None = None
        self.usage: dict | None = None
        self.event_count = 0
        self.tools: dict[str, dict] = {}

    def line(self, raw: bytes) -> None:
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError):
            return  # Some installed CLIs also print startup notices.
        if not isinstance(item, dict):
            return
        kind = item.get("type", "")
        event = {"backend": self.backend, "event": sanitize_text(kind, 100)}
        activities = []
        self.event_count += 1
        if self.backend == "codex":
            if kind == "thread.started":
                self.session_id = item.get("thread_id") if isinstance(item.get("thread_id"), str) else None
            elif kind == "turn.completed":
                self.finished = True
                self.usage = item.get("usage")
            elif kind in ("turn.failed", "error"):
                error = item.get("error") or item.get("message") or "Codex task failed"
                self.error = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            elif kind in ("item.started", "item.updated", "item.completed") and isinstance(item.get("item"), dict):
                details = item["item"]
                event["item_type"] = sanitize_text(details.get("type"), 80)
                if isinstance(details.get("id"), str):
                    event["item_id"] = sanitize_text(details["id"], 100)
                if kind == "item.completed" and details.get("type") == "agent_message":
                    self.final = details.get("text")
                if details.get("type") == "command_execution" and (details.get("exit_code") is None or type(details.get("exit_code")) is int):
                    event["exit_code"] = details.get("exit_code")
                activity = _codex_activity(kind, details)
                if activity:
                    activities.append(activity)
        else:
            if isinstance(item.get("session_id"), str):
                self.session_id = item["session_id"]
            if kind == "result":
                self.finished = item.get("subtype") == "success" and item.get("is_error") is not True
                if not self.finished:
                    self.error = str(item.get("errors") or item.get("result") or item.get("subtype") or "Claude task failed")
                elif item.get("permission_denials"):
                    self.error = "Claude denied one or more required tool permissions. Review the CLI permissions before retrying."
                self.final = item.get("structured_output", item.get("result"))
                self.usage = item.get("usage")
            elif kind == "system" and item.get("subtype") == "permission_denied":
                self.error = "Claude denied a tool permission. Review the CLI permissions before retrying."
            elif kind in ("assistant", "user") and isinstance(item.get("message"), dict):
                content = item["message"].get("content", [])
                for block in content[:100] if isinstance(content, list) else []:
                    if not isinstance(block, dict):
                        continue
                    if kind == "assistant" and block.get("type") == "tool_use":
                        activity = _claude_tool_activity(block)
                        tool_id = block.get("id")
                        if isinstance(tool_id, str) and len(tool_id) <= 200 and len(self.tools) < 1000:
                            self.tools[tool_id] = activity
                        activities.append(activity)
                    elif kind == "user" and block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id")
                        previous = self.tools.pop(tool_id, None) if isinstance(tool_id, str) else None
                        activity = dict(previous or {"kind": "tool", "text": "Tool finished"})
                        activity["status"] = "failed" if block.get("is_error") is True else "completed"
                        activities.append(activity)
                    elif kind == "assistant" and block.get("type") == "text":
                        message = _public_message(block.get("text"))
                        if message:
                            activities.append({"kind": "message", "text": message})
        if self.callback and self.event_count <= 5000:
            if self.session_id:
                event["session_id"] = sanitize_text(self.session_id, 200)
            usage = _usage_summary(item.get("usage"))
            if usage:
                event["usage"] = usage
            for activity in activities or [None]:
                self.callback(redact({**event, "activity": activity} if activity else event))

    def result(self) -> dict:
        if self.error:
            raise RuntimeError(sanitize_text(self.error, MAX_ERROR_CHARS))
        if not self.finished:
            raise RuntimeError(f"{self.backend} exited without a successful terminal event. The task is not marked complete.")
        result = _result_object(self.final)
        if isinstance(self.session_id, str):
            result["session_id"] = self.session_id
        if isinstance(self.usage, dict):
            result["usage"] = self.usage
        return redact(result)


def run_coding_task(backend: str, model: str, cwd: Path, prompt: str, timeout: float,
                    *, event_callback: Callable | None = None) -> dict:
    """Run one independent local CLI session, with bounded output and lifetime."""
    _validate_backend(backend)
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Coding task timeout must be a positive finite number")
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("Coding task working directory must exist")
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 8_000_000:
        raise ValueError("Coding task prompt must be text smaller than 8 MB")
    command = _command(backend) + _arguments(backend, model)
    environment = dict(os.environ)
    # The launcher already found a working interpreter, often a local .venv or
    # Miniconda on Windows. Make it available to the commands the agent runs.
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    options: dict = {"cwd": cwd, "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                     "stderr": subprocess.PIPE, "shell": False, "env": environment}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    with _ACTIVE_LOCK:
        if _CANCELLED.is_set():
            raise RuntimeError("Coding task cancelled before launch")
        process = subprocess.Popen(command, **options)
        job = None
        if os.name == "nt":
            try:
                job = _WindowsJob(process)
            except OSError:
                _stop_process_tree(process)
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()
                raise
        _ACTIVE[process.pid] = (process, job)
    messages: queue.Queue = queue.Queue(maxsize=128)
    stopping = threading.Event()

    def offer(value):
        while not stopping.is_set():
            try:
                messages.put(value, timeout=0.1)
                return
            except queue.Full:
                pass

    def read_pipe(name, pipe):
        try:
            while not stopping.is_set():
                chunk = pipe.read1(8192)
                if not chunk:
                    break
                offer((name, chunk))
        except (OSError, ValueError):
            pass
        finally:
            offer((name, None))

    def write_prompt():
        try:
            process.stdin.write((prompt + "\n" + RESULT_INSTRUCTIONS).encode("utf-8"))
            process.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    readers = [threading.Thread(target=read_pipe, args=(name, pipe), daemon=True)
               for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))]
    writer = threading.Thread(target=write_prompt, daemon=True)
    for worker in readers + [writer]:
        worker.start()
    deadline = time.monotonic() + timeout
    transcript = _Transcript(backend, event_callback)
    pending = b""
    diagnostic = b""
    size = 0
    closed = set()
    children_stopped = False
    try:
        while len(closed) < 2 or process.poll() is None:
            if _CANCELLED.is_set():
                raise RuntimeError("Coding task cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{backend} task exceeded {timeout:g} seconds; its CLI and child commands were stopped.")
            if process.poll() is not None and not children_stopped:
                # A CLI may leave a background command holding its stdout pipe.
                # Keep task lifetime bounded by the CLI, not that orphan process.
                if job:
                    job.terminate()
                else:
                    _stop_process_tree(process)
                children_stopped = True
            try:
                stream, chunk = messages.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if chunk is None:
                closed.add(stream)
                continue
            size += len(chunk)
            if size > MAX_OUTPUT_BYTES:
                raise RuntimeError("Coding CLI output exceeded the 32 MB limit; task stopped.")
            if stream == "stderr":
                diagnostic = (diagnostic + chunk)[-MAX_ERROR_CHARS * 4:]
                continue
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if len(line) > MAX_LINE_BYTES:
                    raise RuntimeError("Coding CLI emitted an oversized event; task stopped.")
                transcript.line(line)
            if len(pending) > MAX_LINE_BYTES:
                raise RuntimeError("Coding CLI emitted an oversized event; task stopped.")
        if pending.strip():
            transcript.line(pending)
        if process.returncode:
            detail = transcript.error or diagnostic.decode("utf-8", "replace").strip() or "Check CLI authentication, model access and permissions."
            raise RuntimeError(redact(f"{backend} exited with code {process.returncode}: {detail[:MAX_ERROR_CHARS]}"))
        return transcript.result()
    except BaseException:
        if job:
            job.terminate()
        _stop_process_tree(process)
        raise
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(process.pid, None)
            if job:
                job.close()
            elif not children_stopped:
                _stop_process_tree(process)
        stopping.set()
        for worker in readers + [writer]:
            worker.join(timeout=1)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe and not pipe.closed:
                pipe.close()
