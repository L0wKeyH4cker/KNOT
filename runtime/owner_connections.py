"""Resolve task owners to explicit model connections, never to another person's key."""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from .security import ENV_RE, contains_secret, register_secret

_FIELDS = {"provider", "model", "credential_ref", "base_url"}
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,199}$")


def connection_error(connection: Any, *, complete: bool = False) -> str | None:
    """Drafts may omit settings; provided values must always be safe and well typed."""
    if not isinstance(connection, dict) or set(connection) - _FIELDS:
        return "Connection must contain only provider, model, credential_ref and optional base_url"
    if contains_secret(connection):
        return "Use a credential environment-variable reference, never an API key in the workflow"
    for key in _FIELDS:
        if key in connection and not isinstance(connection[key], str):
            return f"Connection {key} must be text"
    provider = connection.get("provider", "")
    if provider and provider not in ("openai", "anthropic"):
        return "Connection provider must be openai or anthropic"
    model = connection.get("model", "").strip()
    if model and (not _MODEL.fullmatch(model) or re.match(r"^[A-Za-z]:", model)
                  or any(part in (".", "..") for part in model.split("/"))):
        return "Connection model must be a model identifier, not a command or path"
    ref = connection.get("credential_ref", "")
    if ref and not ENV_RE.fullmatch(ref):
        return "Connection credential_ref must be an uppercase environment-variable name"
    base = connection.get("base_url", "").strip()
    if base:
        try:
            parsed = urlparse(base)
            _ = parsed.port
            valid = (len(base) <= 2048 and not any(ord(c) < 33 for c in base)
                     and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
                     and (parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")))
        except ValueError:
            valid = False
        if not valid:
            return "Connection base_url must use HTTPS (or loopback HTTP) without credentials"
    if complete and (not provider or not model or not ref):
        return "Configure this task owner's provider, model and credential reference before using OpenCode"
    return None


def resolve_owner_connection(workflow: dict, node: dict) -> dict:
    """Return only non-secret routing metadata; key values remain in the runner environment."""
    owner_id = node.get("config", {}).get("owner_id")
    members = workflow.get("project", {}).get("members", [])
    owner = next((m for m in members if isinstance(m, dict) and m.get("id") == owner_id), None)
    if owner is None:
        raise ValueError("Assign an existing task owner before using OpenCode")
    connection = owner.get("connection")
    if connection is None:
        raise ValueError("Configure this task owner's model connection before using OpenCode")
    error = connection_error(connection, complete=True)
    if error:
        raise ValueError(error)
    return {"owner_id": owner_id, "owner_name": owner["name"],
            "provider": connection["provider"], "model": connection["model"].strip(),
            "credential_ref": connection["credential_ref"], "base_url": connection.get("base_url", "").strip().rstrip("/")}


def register_owner_secrets(workflow: Any) -> None:
    """Register custom reference names too, even when they do not contain KEY or TOKEN."""
    project = workflow.get("project") if isinstance(workflow, dict) else None
    members = project.get("members") if isinstance(project, dict) else None
    for member in members if isinstance(members, list) else []:
        connection = member.get("connection") if isinstance(member, dict) else None
        ref = connection.get("credential_ref") if isinstance(connection, dict) else None
        if isinstance(ref, str) and ENV_RE.fullmatch(ref):
            register_secret(os.environ.get(ref, "").strip())


def validate_owner_connections(workflow: Any, require_credentials: bool = False) -> list[dict]:
    """Check only task owners; an unassigned reviewer does not need an API connection."""
    register_owner_secrets(workflow)
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        return [{"severity": "error", "code": "owner_connection", "message": "A valid workflow is required for owner connections"}]
    issues = []
    credential_owners: dict[str, str] = {}
    for node in workflow["nodes"]:
        if not isinstance(node, dict) or node.get("type") != "agent_task":
            continue
        code = "owner_connection"
        try:
            connection = resolve_owner_connection(workflow, node)
            ref = connection["credential_ref"]
            previous_owner = credential_owners.setdefault(ref, connection["owner_id"])
            if previous_owner != connection["owner_id"]:
                code = "owner_credential_duplicate"
                raise ValueError("Different task owners must use separate credential references; assign this owner their own reference")
            if require_credentials and not os.environ.get(connection["credential_ref"], "").strip():
                code = "owner_credential_missing"
                raise ValueError(f"Task owner's credential {connection['credential_ref']} is not configured on this computer")
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            message = str(error) if isinstance(error, ValueError) else "Malformed task owner connection"
            issues.append({"severity": "error", "code": code, "message": message, "node_id": node.get("id")})
    return issues
