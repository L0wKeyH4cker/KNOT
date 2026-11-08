#!/usr/bin/env python3
"""KNOT's local terminal client. Monitoring never starts or stops an agent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "run":
        from run import main as run_main
        return run_main(arguments[1:])
    parser = argparse.ArgumentParser(description="KNOT terminal: watch local agent workflows and their activity")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", help="Start a workflow (run --help lists execution options)")
    for name, help_text in (("monitor", "Live dashboard for local KNOT workflows"), ("status", "Print a status snapshot without starting any work")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--root", action="append", default=[], metavar="FOLDER", help="Also watch this extracted project; repeat for older unregistered runs")
        command.add_argument("--once", action="store_true", help="Print once instead of refreshing the terminal")
        command.add_argument("--json", action="store_true", help="Print a sanitized JSON snapshot and exit")
    if not arguments:
        arguments = ["monitor"]
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.print_help()
        return 0
    from runtime.activity import sanitize_text
    from runtime.monitor import render_dashboard, watch
    from runtime.registry import list_runs
    roots = [Path(value).expanduser().resolve() for value in args.root]
    if not roots and (Path.cwd() / "logs/run-state.json").is_file():
        roots.append(Path.cwd())
    try:
        def read_runs():
            return list_runs(roots=roots)
        if args.json:
            print(json.dumps(read_runs(), ensure_ascii=False, indent=2))
        elif args.command == "status" or args.once:
            width, height = shutil.get_terminal_size((110, 36))
            print(render_dashboard(read_runs(), width=width, height=height))
        else:
            watch(read_runs)
        return 0
    except KeyboardInterrupt:
        print("\nMonitor closed. Workflows continue running in their own terminals.")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print("KNOT monitor: " + sanitize_text(str(error), 500), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
