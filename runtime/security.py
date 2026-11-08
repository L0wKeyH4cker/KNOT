"""Small explicit filesystem and secret boundaries shared by the runtime."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
SECRET_RE = re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b")
MAX_FILE_BYTES = 2_000_000
_REGISTERED_SECRETS: set[str] = set()


def relative_path(value: Any, allowed_roots: tuple[str, ...] = ()) -> str:
    """Reject drive names, traversal, glob grants and Windows alternate streams."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A non-empty relative file path is required")
    value = value.replace("\\", "/")
    parts = value.split("/")
    if value.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError("Absolute paths and path traversal are not allowed")
    if any(c in value for c in (":", "*", "?", "\x00")):
        raise ValueError("Drive names, wildcards and alternate streams are not allowed")
    for part in parts:
        if part.endswith((".", " ")) or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise ValueError("Unsafe platform-specific path")
    if allowed_roots and parts[0] not in allowed_roots:
        raise ValueError(f"Path must be inside {' or '.join(allowed_roots)}/")
    return str(PurePosixPath(value))


def resolve_path(path: Path | str) -> Path:
    resolved = Path(path).resolve()
    # Windows can retain the extended-length prefix when another process holds
    # a newly created file. It denotes the same path, not a different drive.
    if os.name == "nt":
        value = str(resolved)
        if value.startswith("\\\\?\\UNC\\"):
            return Path("\\\\" + value[8:])
        if value.startswith("\\\\?\\") and len(value) > 6 and value[5] == ":":
            return Path(value[4:])
    return resolved


def safe_path(root: Path | str, value: str, allowed_roots: tuple[str, ...]) -> Path:
    relative = relative_path(value, allowed_roots)
    root = resolve_path(root)
    candidate = root.joinpath(*relative.split("/"))
    cursor = root
    for part in relative.split("/"):
        cursor = cursor / part
        try:
            # st_file_attributes is available on Windows even before
            # Path.is_junction (Python 3.12); reject all reparse points.
            reparse_point = bool(getattr(cursor.lstat(), "st_file_attributes", 0) & 0x400)
        except FileNotFoundError:
            reparse_point = False
        if reparse_point or cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise PermissionError("Symlinks and junctions are not allowed in workflow file paths")
    resolved = resolve_path(candidate)
    if not resolved.is_relative_to(root):
        raise PermissionError("File path escapes the run directory")
    # The inputs/results top-level directory itself may not point outside root.
    if not resolved.is_relative_to(root / relative.split("/")[0]):
        raise PermissionError("File path escapes its allowed directory")
    return resolved


def granted_path(root: Path | str, value: str, grants: list[str], write: bool = False) -> Path:
    allowed = ("results",) if write else ("inputs", "results")
    relative = relative_path(value, allowed)
    for grant in grants:
        clean = relative_path(grant.rstrip("/"), allowed)
        if relative == clean or relative.startswith(clean + "/"):
            return safe_path(root, relative, allowed)
    raise PermissionError(f"No {'write' if write else 'read'} permission for {relative}")


def register_secret(value: str) -> None:
    if value:
        _REGISTERED_SECRETS.add(value)


def credential_values() -> list[str]:
    return sorted(_REGISTERED_SECRETS | {v for k, v in os.environ.items() if ("KEY" in k or "TOKEN" in k or "SECRET" in k) and len(v) >= 8}, key=len, reverse=True)


def redact(value: Any) -> Any:
    """Redact provider secrets before any persistent result/log/terminal output."""
    if isinstance(value, str):
        for secret in credential_values():
            value = value.replace(secret, "[REDACTED]")
        return SECRET_RE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {redact(str(k)): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return bool(SECRET_RE.search(value)) or any(s in value for s in credential_values())
    if isinstance(value, dict):
        return any(str(k).lower() in {"api_key", "apikey", "access_token", "authorization", "secret"} or contains_secret(str(k)) or contains_secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(v) for v in value)
    return False


def load_env(path: Path) -> None:
    """Read simple KEY=value .env files without interpolation or execution."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if ENV_RE.fullmatch(key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
