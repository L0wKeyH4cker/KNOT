#!/usr/bin/env python3
"""Run an extracted OpenCode example with keys saved in this local editor.

No credentials are copied into the extracted folder. Only an explicit invocation
without --validate starts model tasks; validation never makes a model request.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

EDITOR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR_ROOT))

from runtime.local_config import load_execution
from runtime.security import load_env, redact, safe_path
from run import main as run_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", help="Extracted OpenCode ZIP folder containing workflow.json")
    parser.add_argument("--validate", action="store_true", help="Check configuration and CLI only; no model requests")
    parser.add_argument("--plain", action="store_true", help="Show scrolling logs")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry failed tasks")
    args = parser.parse_args(argv)
    if args.validate and args.retry_failed:
        parser.error("Choose --validate or --retry-failed")
    try:
        folder = args.folder or input("Paste the extracted OpenCode folder path, then press Enter: ")
        if not folder.strip():
            raise ValueError("An extracted folder is required; no tasks were started.")
        root = Path(folder.strip().strip('"')).expanduser().resolve()
        workflow = safe_path(root, "workflow.json", ("workflow.json",))
        if not workflow.is_file():
            raise ValueError("Choose the extracted folder containing workflow.json, not the ZIP file.")
        if load_execution(root)["backend"] != "opencode":
            raise ValueError("Export the example with Run with = OpenCode before using this helper.")
        for name in (".env.local", ".env"):
            load_env(safe_path(EDITOR_ROOT, name, (name,)))
        # Reuse the task-local installation if present, without changing the
        # user's global PATH or installing another CLI. Otherwise use normal PATH.
        binary_dir = EDITOR_ROOT / ".tools/opencode-cli/node_modules/@opencode/cli/bin"
        binary = binary_dir / ("opencode.exe" if os.name == "nt" else "opencode")
        if binary.is_file():
            os.environ["PATH"] = str(binary_dir) + os.pathsep + os.environ.get("PATH", "")
        print("Using member keys saved in this editor (existing environment variables take precedence).")
        print("No keys are copied to the export. " + ("Checking only; no model calls." if args.validate else "Starting OpenCode tasks; your providers may charge for model calls."))
        options = ["--root", str(root), "--workflow", str(workflow), "--interactive"]
        if args.validate:
            options.append("--validate")
        if args.plain:
            options.append("--plain")
        if args.retry_failed:
            options.append("--retry-failed")
        return run_workflow(options)
    except (OSError, ValueError, EOFError) as error:
        print(redact(f"KNOT example: {error}"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
