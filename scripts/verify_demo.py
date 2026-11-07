"""Export and verify the demo in an isolated folder; explicitly simulate reviewer approval.

This is an acceptance script, not the end-user runner. Normal bundles always wait
for the person's explicit approval and never run this script.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.bundle import build_bundle  # noqa: E402
from backend.template import load_template  # noqa: E402


def main():
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    scratch = ROOT / ".test-tmp"
    scratch.mkdir(exist_ok=True)
    workflow = load_template()
    bundle = build_bundle(workflow)
    (artifacts / "knot-demo.zip").write_bytes(bundle)
    with tempfile.TemporaryDirectory(prefix="final-demo-", dir=scratch) as folder:
        run_root = Path(folder)
        with zipfile.ZipFile(artifacts / "knot-demo.zip") as archive:
            archive.extractall(run_root)
        first = subprocess.run([sys.executable, "-X", "utf8", "run.py", "--mode", "mock"], cwd=run_root, capture_output=True, text=True, encoding="utf-8", timeout=30)
        state = json.loads((run_root / "logs/run-state.json").read_text(encoding="utf-8"))
        assert first.returncode == 2 and state["status"] == "waiting_review", first.stderr
        before = {name: (run_root / "results" / name).exists() for name in ("report.md", "summary.csv")}
        assert not any(before.values()), "Final delivery appeared before approval"
        review = next(n for n in workflow["nodes"] if n["type"] == "human_review")
        resumed = subprocess.run([sys.executable, "-X", "utf8", "run.py", "--mode", "mock", "--resume", "--review", review["id"], "--decision", "approve", "--reviewer", review["config"]["owner_id"]], cwd=run_root, capture_output=True, text=True, encoding="utf-8", timeout=30)
        state = json.loads((run_root / "logs/run-state.json").read_text(encoding="utf-8"))
        assert resumed.returncode == 0 and state["status"] == "completed", resumed.stderr
        destination = artifacts / "demo-results"
        destination.mkdir(exist_ok=True)
        for path in ("results/report.md", "results/summary.csv", "logs/events.jsonl", "logs/run-state.json"):
            source = run_root / path
            assert source.is_file()
            shutil.copyfile(source, destination / source.name)
        evidence = {
            "bundle": "artifacts/knot-demo.zip",
            "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
            "mode": "mock",
            "first_exit_code": first.returncode,
            "first_status": "waiting_review",
            "files_before_approval": before,
            "review_confirmation": "explicitly simulated by scripts/verify_demo.py for acceptance testing",
            "resume_exit_code": resumed.returncode,
            "final_status": state["status"],
            "outputs": ["artifacts/demo-results/report.md", "artifacts/demo-results/summary.csv"],
            "real_api_verified": False,
            "node_statuses": {nid: node["status"] for nid, node in state["nodes"].items()},
        }
        (artifacts / "demo-verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Demo verified: isolated ZIP -> waiting_review (no delivery) -> explicit test approval -> report.md + summary.csv.")


if __name__ == "__main__":
    main()
