"""Assemble a portable, fixed executor plus the exact reviewed workflow."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import zipfile

from runtime.validation import validate_workflow
from runtime.security import contains_secret

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
SECRET_PATTERN = re.compile(r"(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{20,})")


class BundleError(ValueError):
    def __init__(self, message, issues=None):
        super().__init__(message)
        self.issues = issues or []


def reject_secrets(value):
    """Reject known key values and common literal key patterns before serialization."""
    if contains_secret(value):
        raise BundleError("发现凭证字段或 API key。请删除真实凭证，仅保留环境变量引用。")
    text = json.dumps(value, ensure_ascii=False)
    if SECRET_PATTERN.search(text):
        raise BundleError("发现疑似 API key。请删除真实凭证，仅保留环境变量引用。")
    refs = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    if isinstance(value, dict):
        for agent in value.get("agents", []):
            if isinstance(agent, dict) and isinstance(agent.get("credential_ref"), str):
                refs.add(agent["credential_ref"])
        planner = value.get("planner")
        if isinstance(planner, dict) and isinstance(planner.get("credential_ref"), str):
            refs.add(planner["credential_ref"])
    for ref in refs:
        key = os.environ.get(ref, "")
        if len(key) >= 8 and key in text:
            raise BundleError("工作流包含环境凭证值，已拒绝保存或导出。")


def resource_archive_path(path):
    if not isinstance(path, str) or "\\" in path or ":" in path or "\x00" in path:
        raise BundleError("资料路径必须是 inputs/ 内的相对路径。")
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or pure.parts[0] != "inputs" or len(pure.parts) < 2:
        raise BundleError("资料路径必须是 inputs/ 内的相对路径。")
    if any(part in (".", "..") or part.endswith((".", " ")) for part in path.split("/")):
        raise BundleError("资料路径不能包含父目录或不安全文件名。")
    if any(re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I) for part in pure.parts):
        raise BundleError("资料路径包含 Windows 保留文件名。")
    return str(pure)


START_SH = r'''#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then PYTHON=python3
elif command -v python >/dev/null 2>&1; then PYTHON=python
else echo "Python 3.10+ is required. Install it from https://www.python.org/downloads/"; exit 1; fi
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "Python 3.10+ is required."; exit 1; }
if [ ! -x .venv/bin/python ]; then "$PYTHON" -m venv --without-pip .venv; fi
if [ ! -f .env ]; then cp .env.example .env; fi
# No third-party packages are required by this fixed runtime.
if [ "$#" -eq 0 ]; then set -- --mode mock; fi
exec .venv/bin/python run.py "$@"
'''

START_BAT = r'''@echo off
setlocal
cd /d "%~dp0"
set "KNOT_PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "KNOT_PY=python"
if defined KNOT_PY goto python_found
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "KNOT_PY=py -3"
if defined KNOT_PY goto python_found
if exist "%USERPROFILE%\miniconda3\python.exe" set KNOT_PY="%USERPROFILE%\miniconda3\python.exe"
if defined KNOT_PY goto python_found
echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
exit /b 1
:python_found
%KNOT_PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
if exist ".venv\Scripts\python.exe" goto venv_ready
%KNOT_PY% -m venv --without-pip .venv
if errorlevel 1 exit /b 1
:venv_ready
if not exist .env copy .env.example .env >nul
rem This fixed runtime has no third-party dependency to install.
if "%~1"=="" (
  ".venv\Scripts\python.exe" run.py --mode mock
) else (
  ".venv\Scripts\python.exe" run.py %*
)
exit /b %errorlevel%
'''


def bundle_readme(workflow, missing):
    reviews = [n for n in workflow["nodes"] if n["type"] == "human_review"]
    review_commands = "\n".join(
        f"python run.py --mode mock --resume --review {n['id']} --decision approve --reviewer {n['config']['owner_id']}"
        for n in reviews
    ) or "# This workflow contains no human review node."
    model_rows = "\n".join(
        f"- {a['name']}: provider `{a['provider']}`, model `{a.get('model') or '(must be configured for real)'}`, credential `{a['credential_ref']}`."
        for a in workflow.get("agents", [])
    )
    missing_rows = "\n".join(f"- `{p}`" for p in missing) or "None. All declared inline resources are included."
    return f'''# KNOT local workflow package

Project: **{workflow['project']['name']}**

This package contains the fixed, tested Python executor and the workflow exactly as exported from the canvas. It does not call the KNOT editor/backend. Layout changes do not change execution; node configuration and dependency changes do.

## Start (Python 3.10+)

On Windows run `start.bat`. On macOS/Linux run `sh start.sh`. These scripts check Python and create a local `.venv`. The executor uses only the Python standard library; no paid API is called in the default **mock** mode.

Or run directly:

```sh
python run.py --mode mock
```

Mock mode uses fixed sample results, not AI. It still executes dependency scheduling, file permissions, conditions, and human review. Mock examples do not establish research findings.

## Human review: deliberate pause

The process exits with code **2** when waiting for review. This is a pause, not a failure. Inspect `logs/run-state.json` and the drafts held there. Final output files are not produced until the control path reaches an Output node. Approve one waiting review explicitly, using the owner ID shown in the workflow:

```sh
{review_commands}
```

Run the corresponding command only for a review that is actually waiting. Use `--decision reject` to stop that branch. A reviewer ID is a local acknowledgement, not authenticated identity. Use the same `--mode` when resuming. The state records the decision and rejects resume against a different workflow.

## Real model execution

1. Copy `.env.example` to `.env` if the launcher has not already done so.
2. Put your keys only in `.env` or process environment variables.
3. Set each agent's `model` in `workflow.json` to a model supported by your account. Planner configuration in the editor is independent of execution agents.
4. Replace example inputs with your actual permitted project materials.
5. Run `python run.py --mode real` (or `start.bat --mode real` / `sh start.sh --mode real`).

{model_rows}

Real mode fails explicitly if a key/model is missing or an API call fails. It never falls back to mock. Only usage returned by the provider is logged; there is no fabricated cost estimate. Real calls may incur provider charges. No real API call was verified when this package was exported.

## Inputs you must provide

{missing_rows}

`inputs/` contains declared resources only. Resources marked `example: true` are fictional demo inputs. No files are read from the editor computer during bundling. If a resource has no inline content, create the named file before running. Credentials and developer-machine paths are never bundled.

## Files and permissions

- `workflow.json`: single source of truth for nodes, links, agents, owners, resource references, output mappings and limits.
- `prompts/`: readable copies of role system prompts. The executor reads `workflow.json`; editing only a prompt copy will not change the run.
- `results/`: final files and any tool writes explicitly permitted by the workflow.
- `logs/`: per-node state, decisions, errors and execution events. Treat project content in logs as private.
- `run.py`, `runtime/`: fixed executor with OpenAI-compatible Chat Completions and Anthropic Messages adapters.
- `.env.example`: credential variable names only.

Solid control edges decide when nodes can run. Data edges explicitly select which upstream results a node can read. Both must form a DAG. `all_selected` waits for all dependencies to settle and continues if at least one control input is selected; `all_success` requires all control inputs. Nonselected conditional branches are skipped. Failed inputs block descendants.

Agent tools are the intersection of agent and task tool permissions. Reads/writes are restricted to declared relative `inputs/` and `results/` grants. There is no shell or arbitrary code execution. Choosing a human owner grants no file or credential access.

For a completely new run, extract the ZIP into a fresh directory and run the original command without `--resume`. Existing state is deliberately not overwritten. Keep the previous run's logs/results for comparison. A run-state file is trusted local project state: do not resume a state file received from an untrusted person.
'''


def build_bundle(workflow):
    reject_secrets(workflow)
    issues = validate_workflow(workflow, mode="mock")
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        raise BundleError("工作流检查未通过，请修复错误后再导出。", errors)
    refs = sorted({a["credential_ref"] for a in workflow.get("agents", [])})
    if any(not ENV_NAME.fullmatch(ref) for ref in refs):
        raise BundleError("凭证引用必须是大写环境变量名称，不能是真实 API key。")
    contents = {}
    resource_paths = set()
    missing = []
    for resource in workflow.get("resources", []):
        path = resource_archive_path(resource["path"])
        if path.casefold() in resource_paths:
            raise BundleError("两个资料引用使用了同一个文件路径，请先合并或改名。")
        resource_paths.add(path.casefold())
        if "content" in resource:
            if not isinstance(resource["content"], str):
                raise BundleError("示例资料内容必须是文本。")
            contents[path] = resource["content"]
        else:
            missing.append(path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("workflow.json", json.dumps(workflow, ensure_ascii=False, indent=2))
        archive.writestr("run.py", (PROJECT_ROOT / "run.py").read_bytes())
        runtime_files = sorted((PROJECT_ROOT / "runtime").glob("*.py"))
        if not runtime_files:
            raise BundleError("固定执行器尚不可用。")
        for path in runtime_files:
            archive.writestr(f"runtime/{path.name}", path.read_bytes())
        for index, agent in enumerate(workflow.get("agents", []), 1):
            archive.writestr(f"prompts/agent-{index:02d}.md", f"# {agent['name']}\n\nRole: {agent['role']}\n\n{agent['system_prompt']}\n")
        for path, content in contents.items():
            archive.writestr(path, content)
        if "inputs/readme.txt" not in resource_paths:
            archive.writestr("inputs/README.txt", "Only declared project inputs belong here. Files marked example in workflow.json are fictional teaching data.\n")
        archive.writestr("results/README.txt", "Final Output-node deliverables appear here after required human approval. Explicitly permitted tool writes may also appear here.\n")
        archive.writestr("logs/README.txt", "Execution events and run-state.json are written here. State includes drafts before human review. Do not publish private project content.\n")
        archive.writestr(".env.example", "# Store real credentials only in local .env or process environment.\n" + "\n".join(f"{ref}=" for ref in refs) + "\n")
        archive.writestr("requirements.txt", "# Python 3.10+; the executor uses only the standard library.\n")
        archive.writestr("start.bat", START_BAT.replace("\n", "\r\n"))
        info = zipfile.ZipInfo("start.sh")
        info.external_attr = 0o755 << 16
        archive.writestr(info, START_SH)
        archive.writestr("README.md", bundle_readme(workflow, missing))
    return output.getvalue()
