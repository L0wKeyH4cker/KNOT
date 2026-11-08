"""One shared local coding backend for every role in a workflow."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .security import contains_secret, safe_path

DEFAULT_EXECUTION = {
    "schema_version": "1.0",
    "backend": None,
    "model": "",
    "task_timeout_seconds": 1800,
}
BACKENDS = ("codex", "claude")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,199}$")


def validate_execution(value: Any, *, allow_unselected: bool = False) -> dict:
    """Reject secrets, executable paths and unknown options rather than forwarding them."""
    if not isinstance(value, dict):
        raise ValueError("Local execution settings must be an object")
    if set(value) - set(DEFAULT_EXECUTION):
        raise ValueError("Unknown local execution setting; only backend, model and task timeout are supported")
    if contains_secret(value):
        raise ValueError("Local execution settings cannot contain credentials. Use the local assistant's authentication.")
    config = {**DEFAULT_EXECUTION, **value}
    if config["schema_version"] != "1.0":
        raise ValueError("Unsupported local execution settings version")
    backend = config["backend"]
    if backend not in BACKENDS and not (allow_unselected and backend is None):
        raise ValueError("Choose Codex or Claude once: run python run.py --configure, or pass --backend codex / --backend claude")
    model = config["model"]
    if not isinstance(model, str) or (model and (
        not _MODEL.fullmatch(model) or re.match(r"^[A-Za-z]:", model)
        or any(part in (".", "..") for part in model.split("/"))
    )):
        raise ValueError("Model must be an identifier, not a path, command or credential; leave it empty to use the assistant default")
    timeout = config["task_timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError("Local task timeout must be an integer from 1 to 86400 seconds")
    return config


def load_execution(root: Path | str) -> dict:
    path = safe_path(root, "knot.json", ("knot.json",))
    if not path.exists():
        return dict(DEFAULT_EXECUTION)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("knot.json must be a small JSON settings file")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise ValueError("Cannot read knot.json. Fix its JSON or restore it from the exported ZIP.") from error
    return validate_execution(config, allow_unselected=True)


def save_execution(root: Path | str, config: dict) -> None:
    config = validate_execution(config)
    path = safe_path(root, "knot.json", ("knot.json",))
    temporary = safe_path(root, "knot.json.tmp", ("knot.json.tmp",))
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    safe_path(root, "knot.json", ("knot.json",))
    temporary.replace(path)
