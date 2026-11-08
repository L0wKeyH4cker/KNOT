#!/usr/bin/env python3
"""Portable KNOT launcher for local coding assistants and explicit API/mock runs."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

from runtime.engine import Engine, WorkflowError, fingerprint
from runtime.local_config import load_execution, save_execution, validate_execution
from runtime.security import load_env, redact, safe_path
from runtime.validation import validate_workflow
from runtime.owner_connections import validate_owner_connections


def check_backend(backend: str) -> dict:
    from runtime.coding import check_backend as check
    return check(backend)


def run_engine(engine: Engine, mode: str, *, plain: bool = False, tui: bool = False, splash: bool = True) -> dict:
    from runtime.registry import RunRegistration, list_runs
    if mode == "local":
        from runtime.coding import reset_cancellation
        reset_cancellation()

    def interrupt(signum, frame):
        if mode == "local":
            from runtime.coding import cancel_all
            cancel_all()
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGINT, interrupt)
    try:
        with RunRegistration(engine.root, engine.state_path, engine.state["run_id"]) as registration:
            interactive_terminal = bool(sys.stdout.isatty() and sys.stdin.isatty())
            dashboard = not plain and interactive_terminal and (mode == "local" or tui)
            if not dashboard:
                result = engine.run()
            else:
                from runtime.monitor import watch
                stopped = threading.Event()
                outcome = {}
                engine.quiet = True
                def execute():
                    try:
                        outcome["result"] = engine.run()
                    except BaseException as error:
                        outcome["error"] = error
                    finally:
                        stopped.set()
                worker = threading.Thread(target=execute, name="knot-workflow")
                worker.start()
                try:
                    try:
                        reason = watch(lambda: list_runs(roots=[engine.root]), stop_event=stopped, embedded=True, splash=splash)
                    except (OSError, ValueError, RuntimeError):
                        # A display failure must not cancel healthy coding jobs.
                        reason = "plain"
                    if reason in ("closed", "plain") and not stopped.is_set():
                        engine.quiet = False
                        print("Dashboard closed or unavailable; execution continues with logs. Open another terminal with: python knot.py monitor", flush=True)
                    worker.join()
                finally:
                    if not stopped.is_set():
                        if mode == "local":
                            from runtime.coding import cancel_all
                            cancel_all()
                        worker.join()
                    engine.quiet = False
                if "error" in outcome:
                    raise outcome["error"]
                result = outcome["result"]
        if registration.warning:
            print("KNOT monitor discovery: " + registration.warning + " Watch this folder directly with --root.", file=sys.stderr)
        return result
    finally:
        signal.signal(signal.SIGINT, previous)


def choose_backend(current: str | None) -> str:
    print("Choose how to run the Agents in this workflow:")
    print("  1. Codex\n  2. Claude\n  3. OpenCode (each task owner's API connection)")
    if current:
        print(f"Current: {current}. Press Enter to keep it.")
    while True:
        try:
            answer = input("Assistant [1/2/3]: ").strip().lower()
        except EOFError as error:
            raise ValueError("No assistant selected. Pass --backend codex, --backend claude or --backend opencode, or open start.bat in a terminal.") from error
        if not answer and current:
            return current
        if answer in ("1", "codex"):
            return "codex"
        if answer in ("2", "claude"):
            return "claude"
        if answer in ("3", "opencode"):
            return "opencode"
        print("Enter 1 for Codex, 2 for Claude or 3 for OpenCode.")


def configure_execution(root: Path, args: argparse.Namespace, can_prompt: bool) -> tuple[dict, bool]:
    config = load_execution(root)
    changed = False
    if args.backend is not None:
        config["backend"] = args.backend
        changed = True
    elif (args.configure or config["backend"] is None) and can_prompt and not args.validate:
        config["backend"] = choose_backend(config["backend"])
        changed = True
    if args.model is not None:
        config["model"] = args.model
        changed = True
    elif changed and config["backend"] == "opencode":
        config["model"] = ""
    return validate_execution(config), changed


def show_state(state: dict, state_path: Path, mode: str, root: Path) -> None:
    print(f"KNOT mode={mode} status={state['status']}")
    for nid, item in state["nodes"].items():
        print(redact(f"  {nid}: {item['status']}" + (f" — {item['error']}" if item.get("error") else "")))
        if item["status"] == "waiting_review":
            print(redact(f"  Review instructions: {item['instructions']}"))
            print("  Inspect the saved drafts, then explicitly approve or reject:")
            print(f"  python run.py --mode {mode} --resume --review {nid} --decision approve --reviewer {item['owner_id']}")
    print("State: " + str(state_path))
    for result in state.get("results", {}).values():
        if isinstance(result.get("data"), dict) and isinstance(result["data"].get("files"), list):
            for name in result["data"]["files"]:
                label = "Delivered: " if state["status"] == "completed" else "Task file (draft): "
                print(redact(label + str(name)))
    if mode == "local" and state["status"] == "completed":
        project = root / "results" / "project"
        if project.is_dir():
            print("Project files: " + str(project))


def ask_review(state: dict, root: Path) -> tuple[str, str, str] | None:
    waiting = [(nid, item) for nid, item in state["nodes"].items() if item["status"] == "waiting_review"]
    if not waiting:
        return None
    nid, item = waiting[0]
    print(redact(f"\nHuman review: {nid} (owner: {item['owner_id']})\n{item['instructions']}"))
    for source in item.get("input_nodes", []):
        result = state.get("results", {}).get(source, {})
        content = result.get("content", "")
        if isinstance(content, str) and content:
            print(redact(f"\nDraft from {source}:\n{content[:2000]}"))
        if isinstance(result.get("workspace"), str):
            workspace = safe_path(root, result["workspace"], (".knot",))
            if workspace.is_dir():
                print("Inspect files: " + str(workspace))
    print("Review full drafts in logs/run-state.json. Enter approve, reject, or later (default).")
    while True:
        try:
            decision = input("Decision: ").strip().lower()
        except EOFError:
            return None
        if decision in ("", "later", "l"):
            return None
        if decision in ("approve", "a", "reject", "r"):
            return nid, "approve" if decision in ("approve", "a") else "reject", item["owner_id"]
        print("Enter approve, reject, or later. No decision has been recorded.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the canvas workflow with Codex, Claude or owner-configured OpenCode")
    parser.add_argument("--workflow", default="workflow.json", help="Workflow JSON file")
    parser.add_argument("--root", default=".", help="Directory containing knot.json, inputs/, results/ and logs/")
    parser.add_argument("--state", default="logs/run-state.json", help="Relative logs/ state path")
    parser.add_argument("--mode", choices=("local", "mock", "real"), default="local", help="Local coding assistants by default; mock and direct API real are explicit")
    parser.add_argument("--backend", choices=("codex", "claude", "opencode"), help="Local assistant; OpenCode uses each task owner's connection")
    parser.add_argument("--model", help="Optional shared Codex/Claude model; must be empty for owner-configured OpenCode")
    parser.add_argument("--configure", action="store_true", help="Choose and save the shared assistant without starting a run")
    parser.add_argument("--interactive", action="store_true", help="Show assistant selection and explicit human-review prompts")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--plain", action="store_true", help="Use scrolling logs instead of the live terminal dashboard")
    display.add_argument("--tui", action="store_true", help="Show the dashboard in a supported interactive terminal (also in explicit mock mode)")
    parser.add_argument("--no-splash", action="store_true", help="Skip the startup logo and open the dashboard immediately")
    parser.add_argument("--resume", action="store_true", help="Resume a saved human-review pause")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry failed local coding tasks while retaining successful work and old drafts")
    parser.add_argument("--review", help="Waiting Human Review node id")
    parser.add_argument("--decision", choices=("approve", "reject"))
    parser.add_argument("--reviewer", help="Configured human owner's member id")
    parser.add_argument("--validate", action="store_true", help="Check configuration and local CLI availability without starting tasks")
    args = parser.parse_args(argv)
    if args.mode != "local" and (args.backend is not None or args.model is not None or args.configure):
        parser.error("--backend, --model and --configure apply to --mode local")
    if args.retry_failed and args.mode != "local":
        parser.error("--retry-failed applies only to --mode local")
    if args.retry_failed and (args.resume or args.configure or args.validate):
        parser.error("--retry-failed cannot be combined with --resume, --configure or --validate")
    if args.configure and (args.resume or args.validate):
        parser.error("--configure cannot be combined with --resume or --validate")
    if args.resume and not all((args.review, args.decision, args.reviewer)):
        parser.error("--resume requires --review, --decision and --reviewer")
    if not args.resume and any((args.review, args.decision, args.reviewer)):
        parser.error("Review decisions require --resume")
    root = Path(args.root).resolve()
    interactive = args.interactive or (args.mode == "local" and sys.stdin.isatty())
    try:
        for name in (".env", ".env.local"):
            load_env(safe_path(root, name, (name,)))
        execution = None
        changed = False
        if args.mode == "local":
            execution, changed = configure_execution(root, args, interactive and not args.retry_failed)
        if args.configure:
            save_execution(root, execution)
            if execution["backend"] == "opencode":
                print("Saved OpenCode in knot.json. Each task uses its owner's model and API credential reference.")
            else:
                print(f"Saved {execution['backend']} for every Agent in knot.json. Model: {execution['model'] or 'assistant default'}.")
            print("Run start.bat (Windows), sh start.sh (macOS/Linux), or python run.py to begin.")
            return 0
        workflow_path = Path(args.workflow)
        if not workflow_path.is_absolute():
            workflow_path = root / workflow_path
        workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
        if args.validate:
            issues = validate_workflow(workflow, args.mode)
            if execution and execution["backend"] == "opencode":
                issues.extend(validate_owner_connections(workflow, require_credentials=True))
            availability = None
            if execution:
                availability = check_backend(execution["backend"])
                if not availability.get("available"):
                    issues.append({"severity": "error", "code": "backend_unavailable", "message": availability.get("message") or availability.get("error") or f"Install {execution['backend']} locally before running."})
            print(json.dumps(redact({"mode": args.mode, "execution": execution, "backend": availability, "issues": issues}), ensure_ascii=False, indent=2))
            return 1 if any(i["severity"] == "error" for i in issues) else 0
        if changed and not args.retry_failed:
            save_execution(root, execution)
        if execution:
            if execution["backend"] == "opencode":
                print("Using OpenCode with each task owner's model and API connection.")
            else:
                print(f"Using {execution['backend']} for all Agents; model: {execution['model'] or 'assistant default'}.")
            print("Each task has its own workspace. Independent tasks run in parallel according to the canvas.")
        state_path = safe_path(root, args.state, ("logs",))
        saved = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
        if saved is not None and not isinstance(saved, dict):
            raise ValueError("Saved run state is invalid; keep its files and use a fresh exported folder.")
        if execution and (saved is None or saved.get("status") != "completed"):
            availability = check_backend(execution["backend"])
            if not availability.get("available"):
                raise RuntimeError(availability.get("message") or availability.get("error") or f"Install {execution['backend']} locally before running.")
        kwargs = {"execution": execution} if execution is not None else {}
        engine = Engine(workflow, root, args.mode, args.state, **kwargs)
        state = None
        if args.resume:
            engine.resume(args.review, args.decision, args.reviewer)
        elif args.retry_failed:
            engine.retry_failed()
        elif saved is not None:
            if saved.get("workflow_hash") != fingerprint(workflow) or saved.get("mode") != args.mode:
                raise ValueError("This folder already contains a run of a different workflow or mode. Extract a fresh ZIP for a new run.")
            if saved.get("status") == "completed":
                print("This workflow already completed. Existing results have been kept; extract a fresh ZIP for another run.")
                show_state(saved, engine.state_path, args.mode, root)
                return 0
            if saved.get("status") == "waiting_review" and interactive:
                state = saved
            else:
                show_state(saved, engine.state_path, args.mode, root)
                if saved.get("status") == "waiting_review":
                    print("Run python run.py --interactive to review, or use the explicit --resume command above.")
                    return 2
                if args.mode == "local" and saved.get("status") == "failed":
                    raise ValueError("This local run failed. Its logs and drafts are preserved. Use --retry-failed to explicitly retry failed coding tasks, or use a fresh exported folder.")
                raise ValueError("A run already exists. Its logs and workspaces are preserved. Use a fresh exported folder for a new run.")
        if state is None:
            state = run_engine(engine, args.mode, plain=args.plain, tui=args.tui, splash=not args.no_splash)
        while state["status"] == "waiting_review" and interactive:
            decision = ask_review(state, root)
            if decision is None:
                break
            engine.resume(*decision)
            state = run_engine(engine, args.mode, plain=args.plain, tui=args.tui, splash=False)
        show_state(state, engine.state_path, args.mode, root)
        if state["status"] == "waiting_review":
            return 2
        return 1 if state["status"] == "failed" else 0
    except WorkflowError as error:
        print(json.dumps(redact({"status": "invalid", "issues": error.issues}), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Existing run logs and task files have been kept.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError) as error:
        print(redact(f"KNOT error: {error}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
