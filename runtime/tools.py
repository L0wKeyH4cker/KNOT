"""Bounded local tools. Permission checks happen on every invocation."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

from .security import MAX_FILE_BYTES, granted_path, redact

TOOL_DEFINITIONS = {
    "read_text": {"name": "read_text", "description": "Read a permitted UTF-8 text file, at most 2 MB.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    "read_csv": {"name": "read_csv", "description": "Read a permitted CSV as a list of row objects, up to 5000 rows.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    "summarize_csv": {"name": "summarize_csv", "description": "Count CSV rows and summarize numeric columns with sum, min, max and mean.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    "write_file": {"name": "write_file", "description": "Write text to a permitted .md, .json, or .csv file under results/. Never use this to bypass a Human Review gate.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
}


def read_limited(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Required input file is missing: {path.name}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 2 MB tool limit")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        result = handle.read(MAX_FILE_BYTES + 1)
    if len(result.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 2 MB tool limit")
    return result


def parse_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ValueError("CSV requires a header row")
    rows = []
    for row in reader:
        if len(rows) >= 5000:
            raise ValueError("CSV exceeds the 5000 row limit")
        rows.append(row)
    return rows


class ToolRunner:
    def __init__(self, root: Path | str, agent: dict, config: dict, protected_outputs: set[str] | None = None):
        self.root = Path(root)
        self.allowed = set(agent.get("tools", [])) & set(config.get("tools", []))
        self.permissions = config.get("permissions", {"read": [], "write": []})
        self.protected_outputs = {path.replace("\\", "/").casefold() for path in (protected_outputs or set())}

    @property
    def definitions(self) -> list[dict]:
        return [TOOL_DEFINITIONS[name] for name in sorted(self.allowed)]

    def __call__(self, name: str, arguments: dict) -> Any:
        if name not in self.allowed or name not in TOOL_DEFINITIONS:
            raise PermissionError(f"Tool {name} was not granted to both agent and task")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        allowed_args = {"path", "content"} if name == "write_file" else {"path"}
        if set(arguments) - allowed_args:
            raise ValueError("Unexpected tool arguments")
        path = arguments.get("path")
        target = granted_path(self.root, path, self.permissions.get("write" if name == "write_file" else "read", []), write=name == "write_file")
        if name == "write_file":
            relative = target.relative_to(self.root.resolve()).as_posix()
            if relative.casefold() in self.protected_outputs:
                raise PermissionError("This path is reserved for an Output block; an agent cannot bypass final delivery or review")
            if target.suffix.lower() not in (".md", ".json", ".csv"):
                raise PermissionError("write_file only permits Markdown, JSON and CSV")
            content = arguments.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("write_file needs text content no larger than 2 MB")
            if target.suffix.lower() == ".json":
                json.loads(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(redact(content), encoding="utf-8")
            return {"written": relative, "bytes": target.stat().st_size}
        content = read_limited(target)
        if name == "read_text":
            return {"path": path, "content": redact(content)}
        rows = parse_csv(content)
        if name == "read_csv":
            return {"path": path, "rows": redact(rows), "row_count": len(rows)}
        columns = {}
        for column in rows[0] if rows else []:
            numbers = []
            for row in rows:
                try:
                    number = float(row[column])
                    if math.isfinite(number):
                        numbers.append(number)
                except (TypeError, ValueError):
                    pass
            if numbers:
                columns[column] = {"numeric_count": len(numbers), "sum": sum(numbers), "min": min(numbers), "max": max(numbers), "mean": sum(numbers) / len(numbers)}
        return {"path": path, "row_count": len(rows), "numeric_columns": columns}
