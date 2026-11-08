"""OpenCode 2.x task adapter: one private process, config and credential per task.

OpenCode owns its coding tools; these directories isolate connection state, not
operating-system access. No team-wide credentials or user OpenCode settings are
forwarded. The generated config contains an environment reference, never a key.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Callable
from urllib.parse import urlsplit
import uuid

from .activity import sanitize_text
from .security import ENV_RE, redact, register_secret


def isolated_environment(directory: Path) -> dict[str, str]:
    # In particular, do not inherit other owners' keys, an OpenCode server URL,
    # global inline configuration or provider authentication from the launcher.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
               "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
               "PROGRAMDATA", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "SSL_CERT_FILE",
               "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS"}
    env = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                        ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        target = directory / folder
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    config = directory / "config" / "opencode"
    config.mkdir(parents=True, exist_ok=True)
    env.update({"OPENCODE_CONFIG_DIR": str(config), "OPENCODE_CONFIG_PROJECT_DISABLE": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
                "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_FILEWATCHER": "true",
                "NO_COLOR": "1"})
    return env


def connection_config(connection: dict, provider_id: str) -> dict:
    from .owner_connections import connection_error
    if not isinstance(connection, dict) or connection.get("provider") not in ("openai", "anthropic"):
        raise ValueError("OpenCode needs a configured owner connection")
    error = connection_error({key: connection[key] for key in ("provider", "model", "credential_ref", "base_url") if key in connection}, complete=True)
    if error:
        raise ValueError(error)
    model = connection.get("model")
    if not isinstance(model, str) or not model.strip() or len(model) > 200 or any(c in model for c in ("\n", "\r", "\x00", "#")):
        raise ValueError("The owner must select an explicit API model ID")
    base = connection.get("base_url") or (
        "https://api.anthropic.com/v1" if connection["provider"] == "anthropic" else "https://api.openai.com/v1")
    parsed = urlsplit(base)
    if "{" in base or "}" in base:
        raise ValueError("Owner API address cannot contain OpenCode variable substitutions")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (
        parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise ValueError("Owner API address must use HTTPS or loopback HTTP without credentials")
    if connection["provider"] == "anthropic":
        package = "@opencode/ai/providers/anthropic"
    elif parsed.hostname == "api.openai.com":
        package = "@opencode/ai/providers/openai/responses"
    else:
        package = "@opencode/ai/providers/openai-compatible"
    selected = provider_id + "/" + model
    return {
        "model": selected,
        "providers": {provider_id: {
            "name": "KNOT task connection", "package": package, "env": ["KNOT_TASK_API_KEY"],
            "settings": {"apiKey": "{env:KNOT_TASK_API_KEY}", "baseURL": base.rstrip("/")},
            "models": {model: {"name": model, "modelID": model}},
        }},
        "agents": {"knot-worker": {"description": "Execute one assigned KNOT task", "mode": "primary",
                                  "model": selected,
                                  "system": "Perform only the assigned task. KNOT handles scheduling and human review. Do not delegate to subagents. Return the requested completion JSON."}},
        "default_agent": "knot-worker",
        "permissions": [
            {"action": "*", "resource": "*", "effect": "deny"},
            *({"action": action, "resource": "*", "effect": "allow"} for action in ("read", "edit", "shell")),
        ],
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": provider_id, "effect": "allow"},
            {"action": "plugin.load", "resource": "*", "effect": "deny"},
            {"action": "mcp.use", "resource": "*", "effect": "deny"},
        ],
        "snapshots": False,
    }


@contextmanager
def task_environment(connection: dict | None, cwd: Path):
    ref = connection.get("credential_ref") if isinstance(connection, dict) else None
    if not isinstance(ref, str) or not ENV_RE.fullmatch(ref):
        raise ValueError("The task owner needs a credential environment reference")
    key = os.environ.get(ref, "").strip()
    if not key:
        raise ValueError(f"Missing owner credential: {ref}; no other account will be used")
    register_secret(key)
    # Unique provider IDs avoid collision with any managed machine provider.
    config = connection_config(connection, "knot-owner-" + uuid.uuid4().hex)
    with tempfile.TemporaryDirectory(prefix="knot-opencode-") as temporary:
        env = isolated_environment(Path(temporary))
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, ensure_ascii=False)
        env["KNOT_TASK_API_KEY"] = key
        env["PWD"] = str(cwd)
        yield env, config["model"]


class OpenCodeTranscript:
    """Consume public JSONL events; ignore reasoning and reject partial success."""
    def __init__(self, callback: Callable | None):
        self.callback = callback
        self.session_id = None
        self.error = None
        self.finished = False
        self.message_id = None
        self.text_parts: dict[str, str] = {}
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.event_count = 0

    def line(self, raw: bytes) -> None:
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError):
            return
        if not isinstance(item, dict):
            return
        kind = item.get("type")
        if isinstance(item.get("sessionID"), str):
            self.session_id = item["sessionID"]
        part = item.get("part") if isinstance(item.get("part"), dict) else {}
        activity = None
        if kind == "error":
            error = item.get("error")
            self.error = error.get("message", "OpenCode task failed") if isinstance(error, dict) else "OpenCode task failed"
        elif kind == "step_start":
            self.finished = False
            self.message_id = part.get("messageID")
            self.text_parts = {}
        elif kind == "text" and isinstance(part.get("text"), str):
            message = part.get("messageID")
            if message and message != self.message_id:
                self.message_id, self.text_parts = message, {}
                self.finished = False
            part_id = str(part.get("id", "text"))
            self.text_parts[part_id] = self.text_parts.get(part_id, "") + part["text"]
        elif kind == "step_finish":
            self.finished = (part.get("reason") == "stop" and
                             (not part.get("messageID") or part["messageID"] == self.message_id))
            tokens = part.get("tokens")
            if isinstance(tokens, dict):
                for source, target in (("input", "input_tokens"), ("output", "output_tokens")):
                    if type(tokens.get(source)) is int and tokens[source] >= 0:
                        self.usage[target] += tokens[source]
        elif kind == "tool_use":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            tool = sanitize_text(part.get("tool", "tool"), 80)
            activity = {"kind": "tool", "text": tool, "status": "failed" if state.get("status") == "error" else "completed"}
            # A failed attempt can be recovered by a permitted alternative.
            # Completion still requires a final stop event and the task contract.
            arguments = state.get("input") if isinstance(state.get("input"), dict) else {}
            if tool in ("shell", "bash") and isinstance(arguments.get("command"), str):
                activity = {**activity, "kind": "command", "text": sanitize_text(arguments["command"], 1000)}
            elif tool in ("write", "edit", "read") and isinstance(arguments.get("path"), str):
                activity = {**activity, "kind": "file", "text": sanitize_text(tool + " " + arguments["path"], 1000)}
        self.event_count += 1
        if self.callback and self.event_count <= 5000 and kind in ("step_start", "step_finish", "tool_use", "error"):
            self.callback(redact({"backend": "opencode", "event": kind,
                                  "session_id": sanitize_text(self.session_id or "", 200),
                                  **({"activity": activity} if activity else {})}))

    def result(self) -> dict:
        from .coding import _result_object
        if self.error:
            raise RuntimeError(redact(sanitize_text(self.error, 6000)))
        if not self.finished:
            raise RuntimeError("OpenCode exited without a successful terminal event. The task is not marked complete.")
        result = _result_object("".join(self.text_parts.values()))
        result["session_id"] = self.session_id
        result["usage"] = self.usage
        return redact(result)
