#!/usr/bin/env python3
"""Portable KNOT launcher. No third-party Python dependencies required."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.engine import Engine, WorkflowError
from runtime.security import load_env, redact
from runtime.validation import validate_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the exact KNOT workflow in mock or real mode")
    parser.add_argument("--workflow", default="workflow.json", help="Workflow JSON file")
    parser.add_argument("--root", default=".", help="Directory containing inputs/, results/ and logs/")
    parser.add_argument("--state", default="logs/run-state.json", help="Relative logs/ state path")
    parser.add_argument("--mode", choices=("mock", "real"), default="mock")
    parser.add_argument("--resume", action="store_true", help="Resume a saved human-review pause")
    parser.add_argument("--review", help="Waiting Human Review node id")
    parser.add_argument("--decision", choices=("approve", "reject"))
    parser.add_argument("--reviewer", help="Configured human owner's member id")
    parser.add_argument("--validate", action="store_true", help="Validate workflow and credentials without running")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    load_env(root / ".env")
    load_env(root / ".env.local")
    try:
        workflow_path = Path(args.workflow)
        if not workflow_path.is_absolute():
            workflow_path = root / workflow_path
        workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
        if args.validate:
            issues = validate_workflow(workflow, args.mode)
            print(json.dumps(redact({"mode": args.mode, "issues": issues}), ensure_ascii=False, indent=2))
            return 1 if any(i["severity"] == "error" for i in issues) else 0
        if args.resume and not all((args.review, args.decision, args.reviewer)):
            parser.error("--resume requires --review, --decision and --reviewer")
        if not args.resume and any((args.review, args.decision, args.reviewer)):
            parser.error("Review decisions require --resume")
        engine = Engine(workflow, root, args.mode, args.state)
        if args.resume:
            engine.resume(args.review, args.decision, args.reviewer)
        state = engine.run()
        print(f"KNOT mode={args.mode} status={state['status']}")
        for nid, item in state["nodes"].items():
            print(redact(f"  {nid}: {item['status']}" + (f" — {item['error']}" if item.get("error") else "")))
            if item["status"] == "waiting_review":
                print(redact(f"  Review instructions: {item['instructions']}"))
                print(f"  Inspect logs/run-state.json results, then explicitly approve or reject:")
                print(f"  python run.py --mode {args.mode} --resume --review {nid} --decision approve --reviewer {item['owner_id']}")
        print("State: " + str(engine.state_path))
        if state["status"] == "waiting_review":
            return 2
        if state["status"] == "failed":
            return 1
        for result in state["results"].values():
            if isinstance(result.get("data"), dict) and "files" in result["data"]:
                for name in result["data"]["files"]:
                    print("Delivered: " + name)
        return 0
    except WorkflowError as error:
        print(json.dumps(redact({"status": "invalid", "issues": error.issues}), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as error:
        print(redact(f"KNOT error: {error}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
