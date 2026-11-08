"""Safe, compact descriptions of untrusted agent activity for local monitors."""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from .security import redact


# Strip entire terminal control strings, including their payload (OSC can set a
# window title, clipboard, or hyperlink). Strip incomplete strings as well.
_CONTROL_STRING = re.compile(r"(?:\x1b\]|\x9d)[\s\S]*?(?:\x07|\x1b\\|\x9c|$)|(?:\x1b[P^_]|[\x90\x98\x9e\x9f])[\s\S]*?(?:\x1b\\|\x9c|$)")
_CSI = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")
_ESCAPE = re.compile(r"\x1b[ -/]*[@-~]")
_AUTH = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s\"'`,;<>]+")
_SECRET_NAME = r"(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization)|[\w-]+[_-](?:key|token)|token)"
_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?P<prefix>" + _SECRET_NAME + r"[\"']?\s*(?:[:=]\s*|\s+))"
    r"(?P<value>\"[^\"]*(?:\"|$)|'[^']*(?:'|$)|[^\s\"'`,;)&<>]+)"
)
_URL_AUTH = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_PEM = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)")
_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")


def sanitize_text(value: Any, limit: int = 300) -> str:
    """Return bounded single-line text; never interpret CLI text as terminal UI.

    This is a display boundary, not permission to publish raw tool payloads.
    Callers should select command names and paths, never stdout or file content.
    """
    if not isinstance(limit, int) or limit <= 0:
        return ""
    text = "" if value is None else str(value)
    # Parse/mask before truncation so a visible prefix of a secret cannot escape.
    text = _CONTROL_STRING.sub("", text)
    text = _CSI.sub("", text)
    text = _ESCAPE.sub("", text)
    text = "".join(" " if c.isspace() else c for c in text
                   if c.isspace() or unicodedata.category(c) not in {"Cc", "Cf", "Cs"})
    text = redact(text)
    # security.redact also covers registered per-run secrets. Password variables
    # need coverage when this module runs in a separate monitor process.
    for name, secret in os.environ.items():
        if len(secret) >= 8 and any(part in name.upper() for part in ("PASSWORD", "PASSWD", "AUTH")):
            text = text.replace(secret, "[REDACTED]")
    text = _PEM.sub("[REDACTED]", text)
    text = _URL_AUTH.sub(r"\1[REDACTED]@", text)
    text = _AUTH.sub(r"\1 [REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda match: match["prefix"] + "[REDACTED]", text)
    text = _TOKEN.sub("[REDACTED]", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:max(0, limit - 1)] + "…"
