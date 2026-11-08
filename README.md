# KNOT

<img src="public/brand/KNOT-logo.png" alt="KNOT" width="220" />

**Your idea. A team in motion.**

[**Open KNOT online → knot-lovat.vercel.app**](https://knot-lovat.vercel.app/)

KNOT turns a project idea or requirements document into an editable AI workflow. Arrange tasks on a canvas, assign human owners and AI roles, add review gates, and export a workspace that runs with Codex or Claude on your own computer.

Choose one local assistant for the whole workflow. Each task gets its own context and working copy; independent tasks run in parallel, and dependent tasks receive the results connected to them. One model can serve several distinct roles.

- **Visual workflow editor:** tasks, shared resources, parallel branches, conditions, human reviews, and outputs, with undo/redo and JSON import/export.
- **Requirements to workflow:** upload a PDF, TXT, or Markdown file, review the extracted tasks and owners, then generate an editable plan.
- **Local execution:** export a portable ZIP with launchers, task instructions, a live terminal dashboard, and explicit recovery for failed tasks.
- **Human ownership and review:** track who owns each task and require a person's approval before final delivery.
- **Usage and cost sharing:** import execution usage, confirm actual costs, and split them among project members.
- **Project library:** automatic browser drafts and optional Supabase cloud saves.

## Use KNOT online

Visit [https://knot-lovat.vercel.app/](https://knot-lovat.vercel.app/) to start in your browser. You can design, save, and export workflows without cloning this repository or installing Node.js, Python, or a local backend. Python and a coding CLI are needed later to execute the downloaded workspace.

### From idea to running workflow

1. **Explore the app.** On your first visit, click **Explore an example** for a guided tour. You can revisit it through **A quick guide → Take a guided tour**.
2. **Start a project.** Describe your idea and click **Continue**. Enter the project name, goal, and final deliverable, then click **Create project**. To start from a document instead, click **Add requirements** and upload a text PDF, TXT, or Markdown file.
3. **Build or generate your plan.** Choose **Start from scratch** to build the canvas yourself, or **Generate with AI** to open the designer. For a document, review the extracted text, click **Analyze requirements**, edit the proposed tasks and owners, then click **Generate workflow from requirements**.
4. **Review the assignments and handoffs.** Select each task to check its **Agent**, **Human owner**, **Task instructions**, and **Acceptance criteria**. Set the **Reviewer** on Human Review nodes. Control connections set execution order; data connections pass upstream results and project files.
5. **Check and save.** Click **Check** and resolve any errors, then click **Save**. Use **Export JSON** to keep a portable backup. Reopen projects through **My projects** on the home page or **Saved projects** in the sidebar.
6. **Download the workspace.** Click **Export runner**, select **Codex** or **Claude** under **Run with**, and click **Download agent workspace**. Leave **Shared model (optional)** blank to use your local CLI's default model.
7. **Run it on your computer.** Extract the ZIP into a new folder, install Python 3.10+ and authenticate the selected CLI, then follow the [local execution instructions](#export-and-run-local-agents). Keep the run terminal open and approve or reject when the workflow reaches a human review.
8. **Collect results and review costs.** Delivered project files appear in `results/project/`, with configured reports in `results/`. Return to the same online project, open **Costs & split**, and use **Import usage report** to load `logs/usage-report.json`.

The website handles workflow design, requirements analysis, validation, and export. Downloading a workspace does not start its Agents; the run command starts them on your computer. You do not need to install the editor locally to run a downloaded workspace.

### Planning, uploads, and saved projects

The online site supplies a default DeepSeek planning connection. Start with the supplied **Planning provider** and **Planning model** settings; its API credentials are managed on the server, so you do not need to enter a personal key to use that connection. Existing custom planner settings may still be saved in your browser. If generation reports a connection error, check those settings; you can also continue with **Start from scratch** or the example template. The planner connection is separate from the Codex/Claude authentication used to execute tasks locally.

Uploaded requirements are sent to the hosted backend for text extraction. Clicking **Analyze requirements** or generating a workflow sends the extracted text and relevant project materials to the configured planning model. See [Generate from requirements](#generate-from-requirements) for supported files and limits.

Drafts are saved in the current browser. Clicking **Save** also attempts a cloud save when cloud integration is configured; check the save message to see whether it succeeded. Keep workflow backups with **Export JSON**, and use **Import JSON** to move a project to another browser or a local editor. Online and local installations have separate browser storage. Export the cost ledger separately if you need to move it too; it is not part of workflow JSON or cloud saves.

## Run the editor locally

Requirements:

- Node.js 22.12+ or 20.19+ for the editor. Use Node.js 22.12+ if you also want to run the frontend data tests.
- Python 3.10+ for the backend and exported runner.
- A configured planning API only for AI analysis and generation. Manual editing and the example template work without credentials.

From the repository root:

```sh
npm install
python -m pip install --target .tools/python -r requirements.txt
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The development launcher starts Vite and the Python backend on port 8000. The backend uses `pypdf` for requirement PDFs; the exported runner itself uses only the Python standard library.

The launcher checks `PYTHON`, `python3`, `python`, `py -3`, and Miniconda/Anaconda installations in your home directory. If Python is not on PATH, set its location first. For example, in PowerShell:

```powershell
$env:PYTHON = 'C:\path\to\python.exe'
& $env:PYTHON -m pip install --target .tools/python -r requirements.txt
npm run dev
```

You can also start the backend and frontend in separate terminals:

```sh
python server.py --port 8000
```

```sh
npx vite --host 127.0.0.1 --port 5173
```

To serve a production build locally:

```sh
npm run build
python server.py --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The backend serves the built files from `dist/`.

## Create a workflow

1. Describe your idea on the home page and click **Continue** to set the project name, goal, and deliverable. Or click **Add requirements** to start with a document.
2. Choose **Start from scratch**, **Generate with AI**, or the explicitly labeled example template.
3. Drag blocks onto the canvas and connect them. **Control connections** determine when a task starts. **Data connections** determine which upstream results and file changes it receives.
4. Configure each task's instructions, acceptance criteria, Agent, and **Human owner**. Use **Reviewer** for a Human Review node. You can enter names directly without setting up a member list first.
5. Run **Check**, save or export the workflow JSON, then use **Export runner** to download a local workspace.

The **Members** overview in project settings groups tasks and reviews by person. Human owners, AI roles, and model connections are separate: assigning an owner does not grant credentials or file access. The same Agent can perform tasks owned by different people.

Agents, project settings, AI designer, costs, the project library, and help share the same workspace navigation. Returning to **Workflow canvas** preserves the current layout, zoom, and edits. **Read at 100%** restores the canvas to its readable default scale.

### Explore the example

On first visit, **Explore an example** opens a guided tour of the canvas, blocks, connections, task settings, Agents, project settings, AI design, validation, and export. **Back to home** restores your previous project; **×** or **Escape** closes the tour and leaves the example open for editing. After completing or dismissing onboarding, the example opens directly; you can restart the tour from **A quick guide → Take a guided tour**.

The Quick Guide also includes nine illustrated steps with real interface screenshots, chapter navigation, and image enlargement. Viewing the guide does not change your workflow or call a model. The home-page footer links to the GitHub repository.

The sample is a fictional three-person campus mobility study. Two tasks run in parallel, a synthesis task combines their results, and a human review gates delivery of `report.md` and `summary.csv`. Its inputs are teaching examples, not real research data.

### Generate from requirements

For a new project, select **Add requirements** on the home page. For an existing project, open **AI designer → Upload project requirements**.

1. Upload a PDF, TXT, or Markdown file and check the extracted text. You can correct it before analysis.
2. Configure the planner connection and click **Analyze requirements**. Review the goal, deliverables, tasks, acceptance criteria, owners, constraints, and missing information.
3. Edit the task list and each task's **Owner**, then click **Generate workflow from requirements**. You can still edit the generated canvas; one Undo restores the previous workflow.

Named assignments are carried into the task list and checked during generation. The planner is instructed to preserve explicit AI task counts and keep human approval and automatic output collection as separate workflow steps. For example, three AI tasks followed by a person's review should remain three AI tasks plus a Human Review node and an Output node. Planner design notes are requested in the language of the project goal, including during repair attempts.

Local Codex/Claude tasks can create code, PDFs, HTML, charts, slides, and other project files when the required tools, dependencies, and permissions are available. The task's `markdown`, `json`, or `csv` output format describes its report; actual project files are delivered separately. Requirements should retain the requested final deliverable rather than reduce it to an intermediate text report.

File limits are **5 MiB per file**, **40 PDF pages**, and **60,000 extracted characters**. TXT and Markdown must use UTF-8. PDFs need selectable text; OCR for scanned PDFs is not implemented. Unsupported, encrypted, empty, or oversized files produce an error instead of silent truncation.

Text extraction runs on the backend: on your computer when running locally, or on the server when using a hosted editor. Extraction does not call a model. Analysis and generation are separate model requests that use the extracted text. Editing the text invalidates the previous analysis.

Successful generation stores the extracted text and reviewed task list as project resources, included in workflow JSON and exported ZIPs. The original PDF is not included. Uploading, analyzing, or closing the intake view alone does not replace the canvas. See [Requirements guide](docs/REQUIREMENTS.md) for details.

## Export and run local Agents

### Download the workspace

1. Confirm the tasks and connections, then click **Export runner**.
2. Under **Run with**, choose **Codex** or **Claude**. Leave the shared model blank to use your local CLI's default. You do not need a separate model or API key for each role.
3. Click **Download agent workspace** and extract it into a new directory.
4. On the execution computer, install Python 3.10+ and authenticate the selected CLI: [Codex CLI setup](https://developers.openai.com/codex/cli/) or [Claude Code setup](https://code.claude.com/docs/en/setup).
5. Put any starting project code in `workspace/` and supply the materials listed under **Inputs you must provide** in the package.

The ZIP includes its own runner and does not need a running KNOT editor or backend. It does not include credentials from the machine that exported it.

### Start the tasks

On **Windows**, open the extracted folder in File Explorer, confirm that `knot.cmd` and `workflow.json` are present, then type `powershell` in the address bar and press Enter:

```powershell
.\knot.cmd run --interactive
```

On **macOS / Linux**, open a terminal and change to the extracted folder:

```sh
cd "/path/to/extracted-folder"
sh knot.sh run --interactive
```

**One run command dispatches the whole workflow.** The launcher reads the exported assistant selection, starts independent tasks in parallel within the workflow's concurrency limit, and waits for dependencies before starting later tasks. If no assistant was selected during export, it asks once and saves the choice.

Keep the run terminal open while tasks execute. You can also double-click `start.bat` on Windows or run `sh start.sh` on macOS/Linux. If Python is unavailable, install it or activate an existing Python 3.10+ Conda environment before retrying. Activate the same environment in a separate monitor terminal if needed; the launchers locate an available interpreter automatically.

### Monitor progress

Open another terminal in the extracted folder:

| Action                                      | Windows PowerShell                     | macOS / Linux                          |
| ------------------------------------------- | -------------------------------------- | -------------------------------------- |
| Live dashboard                              | `.\knot.cmd monitor`                   | `sh knot.sh monitor`                   |
| One status snapshot                         | `.\knot.cmd status`                    | `sh knot.sh status`                    |
| Validate configuration and CLI availability | `.\knot.cmd run --validate`            | `sh knot.sh run --validate`            |
| Choose a different assistant                | `.\knot.cmd run --configure`           | `sh knot.sh run --configure`           |
| Run with scrolling logs                     | `.\knot.cmd run --interactive --plain` | `sh knot.sh run --interactive --plain` |

`monitor` only reads registered runs; it does not start tasks. `--configure` saves the execution settings and exits; use `run --interactive` afterward in a fresh run directory. To set a shared model, add `--model YOUR_MODEL_ID` to the configure command. `--validate` does not call a model and cannot prove that authentication or model access will work on a real request.

The dashboard shows task states, elapsed time, commands, file changes, and recent activity across local projects.

- Use the arrow keys or `j` / `k` to select a task, and Tab or `n` / `p` to switch projects.
- Press `q` to hide the dashboard while tasks continue. Closing a separate monitor window or pressing `Ctrl+C` there does not stop execution.
- **Pressing `Ctrl+C` in the run terminal stops the local Agents it started.**
- The animated K/workflow mark indicates activity, not percentage complete. Use `--no-splash` to skip the opening logo, `KNOT_NO_ANIMATION=1` to disable animation, or `NO_COLOR=1` to disable colors. Status snapshots, JSON, and redirected output remain plain text.

If Python is already available, `python knot.py run --interactive` and `python knot.py monitor` are equivalent entry points. Use `python knot.py monitor --root "/path/to/older-workspace"` to include an older package's saved status. Re-export older packages to get live command and file activity.

Run discovery stores local directory pointers and heartbeats in `%LOCALAPPDATA%/KNOT/runs` on Windows or `$XDG_STATE_HOME/knot/runs` on macOS/Linux (default `~/.local/state/knot/runs`). Set `KNOT_RUNS_DIR` to override this location. It does not scan the entire disk or upload logs. Monitor summaries omit prompts, result bodies, command output, and private model reasoning, and filter credentials and terminal control characters.

### Review and collect results

At a **Human Review** node, return to the run terminal and inspect the drafts. Enter `approve`, `reject`, or `later`. Pressing Enter also leaves the workflow paused. To handle a saved review later, run the same `run --interactive` command again; completed tasks are not repeated.

After the required review and control path, Output nodes publish project files to `results/project/` and configured reports to `results/`. Before delivery, task working copies remain drafts under `.knot/tasks/`; the run terminal prints their locations. A review pause uses exit code **2**.

| Workspace path           | Purpose                                                  |
| ------------------------ | -------------------------------------------------------- |
| `workflow.json`          | The exported canvas, tasks, resources, and connections   |
| `knot.json`              | Shared local assistant, optional model, and task timeout |
| `workspace/`             | Starting project code supplied before execution          |
| `inputs/`                | Bundled resources and required input materials           |
| `tasks/`, `prompts/`     | Readable task instructions                               |
| `AGENTS.md`, `CLAUDE.md` | Context for coding assistants working with the package   |
| `.knot/tasks/`           | Task working copies and drafts                           |
| `results/`               | Final reports and delivered project files                |
| `logs/run-state.json`    | Saved execution and review state                         |
| `logs/usage-report.json` | Usage summary for import into Costs & split              |

Each task has its own working copy. Control connections set execution order; data connections pass upstream results and code changes. Conflicting file changes stop the affected task instead of silently overwriting files. Source handoffs are limited to **16 MiB per file**, **128 MiB in total**, and **5,000 files**; keep large datasets, model weights, and dependency directories out of these handoffs.

### Retry failed local tasks

After diagnosing the failure, use:

```powershell
.\knot.cmd run --retry-failed --interactive
```

```sh
sh knot.sh run --retry-failed --interactive
```

This backs up the previous state, keeps successful tasks, and retries failed tasks and their blocked downstream work. A failed task's draft is copied into a new attempt directory and must pass normal completion checks before it becomes a successful handoff. The old draft remains intact.

Retry requires an unchanged workflow and execution configuration and a finished run with eligible local task failures. It cannot bypass a rejected human review or recover a run that is still active or whose interrupted state is unresolved. Preserve those records and extract a fresh workspace for a new run. Pending human reviews still require an explicit decision.

Task completion is judged against the assigned deliverables and acceptance criteria. If an allowed alternative method supplies the required evidence, a failed earlier attempt can be reported as a limitation. Explicitly required methods and unfinished acceptance checks still have to be satisfied.

## Track usage and split costs

1. Run an exported workspace, then open **Costs & split** in the same project.
2. Click **Import usage report** and select `logs/usage-report.json`. Re-importing an updated report merges attempts without counting them twice, including failures and retries.
3. In **Execution details**, check each attempt's usage and confirm its amount, currency, and billing evidence. The default payer is the human owner recorded when the task ran; choose **Shared equally** to split a task among selected people.
4. Use **Add shared cost** for planning, subscriptions, or other shared expenses. Avoid adding an expense already included in an execution amount.
5. Review **Member split**, then export execution details, member totals as CSV, or the full ledger as JSON.

Usage and money are tracked separately. Token counts come from the execution provider; a CLI-reported amount is an estimate until confirmed. Unknown usage or cost stays unknown, rather than being treated as free. Only confirmed execution amounts and manually entered shared costs contribute to the split. Changed imported usage can require a previous confirmation to be checked again.

USD, CNY, EUR, and GBP are settled separately without conversion. Member totals are rounded to cents while preserving the overall confirmed total.

The ledger is stored in the current browser, separately from workflow JSON, exported workspaces, and optional cloud saves. Export it before changing devices or deleting a project. This feature does not charge anyone or connect to provider billing accounts. See [Usage and cost sharing](docs/BILLING.md) for the full rules.

## Models and credentials

The **planning model** analyzes requirements and generates a workflow. The **execution backend** carries out its tasks. Configure them separately.

| Execution mode    | Behavior                                                                                                        |
| ----------------- | --------------------------------------------------------------------------------------------------------------- |
| `local` (default) | Uses the installed Codex or Claude CLI, one shared connection, and independent task contexts and working copies |
| `mock` (explicit) | Uses fixed example results to exercise scheduling, conditions, permissions, and review without model API calls  |
| `real` (advanced) | Calls each Agent's configured API with the runner's limited file tools                                          |

Missing CLI access, models, credentials, or required inputs produce an error. A failed real request never silently falls back to mock.

For a **local editor installation**, enter a key in the connection settings and click **Save on this device**, or configure backend environment variables. Saving writes the key to the ignored `.env.local` file, activates it in the backend, and clears the password field. Keys are not persisted in browser storage or exported workspaces. On startup, the backend loads `.env.local` before `.env`, without replacing existing process environment variables.

Workflow files store only environment variable references such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY`. Never put actual keys in nodes, prompts, or workflow JSON. Downloaded workspaces use their own environment; configure any required API keys on the execution machine.

Use the provider's API model ID, not a display name. The DeepSeek preset currently fills in `deepseek-flash`, `https://api.deepseek.com`, and `DEEPSEEK_API_KEY`; change these to match your account when needed. **Test connection** sends a short generic model request without project materials. The connection status only reports whether the backend has a configured key; it does not prove that a generation request has succeeded.

### Advanced: different APIs for different tasks

In **Agents**, configure each role's **Provider**, **Model name**, **Credential reference**, and **API base URL**, then assign that Agent to the appropriate task. These per-Agent connections apply to `--mode real`; the default local mode uses the shared Codex/Claude selection.

| Role     | Protocol           | Model                  | Credential reference |
| -------- | ------------------ | ---------------------- | -------------------- |
| Analyst  | OpenAI-compatible  | Your analysis model ID | `ANALYSIS_API_KEY`   |
| Writer   | Anthropic Messages | Your writing model ID  | `WRITING_API_KEY`    |
| Reviewer | OpenAI-compatible  | Your review model ID   | `REVIEW_API_KEY`     |

Agents can use different endpoints and credentials. Tasks assigned to the same Agent share its connection settings; create separate Agents to use different models. The AI designer's planner does not configure execution models for you.

The runner uses Chat Completions for OpenAI-compatible services and Messages for Anthropic. In the current adapter, official OpenAI `gpt-6*` models use Responses for tasks with tools. Set a base URL without the final `/chat/completions`, `/messages`, or `/responses` path. Third-party services that only implement Responses or native Gemini are not supported by this adapter.

Set the referenced keys in the extracted workspace's `.env`, then run:

```sh
python run.py --mode real --interactive
```

Direct API tools are limited to reading text/CSV, basic CSV summaries, and writing Markdown/JSON/CSV within granted paths. This mode does not provide shell execution or the local coding assistant's tools. Independent tasks can still run in parallel and pass results through data connections.

## Project storage and hosted configuration

Drafts are saved automatically in browser storage. Projects opened from the library use separate tabs and independent drafts. Deletion requires confirmation and removes the local saved project, draft, and cost ledger; other open tabs are prevented from silently recreating the deleted local project. Earlier browser saves are migrated to KNOT without overwriting existing newer saves. Export important workflows as JSON for backup.

The repository also includes a Vercel configuration in `vercel.json` and a Python function entry point in `api/index.py`. A hosted editor still exports workspaces for execution on the user's own computer.

For a hosted planner, `KNOT_HOSTED_PLANNERS` is a server-side JSON allow-list of connections with `credential_ref`, `provider`, `base_url`, and `model` fields. Set the corresponding secrets on the server. When the allow-list is configured, the backend restricts credential references and pins the provider and endpoint; a nonempty configured model also pins the model. Browser requests to save API keys are rejected in this mode.

Optional Supabase integration uses the frontend build variables `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. It expects anonymous authentication and a `workflows` table with `owner`, `project_id`, `name`, `workflow`, and `updated_at`, an owner default based on the authenticated user, uniqueness on `(owner, project_id)`, and row-level policies that restrict access to that owner. Database provisioning and policies must be configured separately.

With cloud integration configured, **Save** writes locally and attempts a cloud save, and the library loads cloud workflows for the current anonymous session. Automatic drafts remain local. If cloud access fails, the app reports it and keeps the local copy. This is not a shared account login, cross-device collaboration, or real-time editing system; cost ledgers are not cloud-synced.

## Development and verification

Run the standard checks from the repository root:

```sh
npm run build
python -m unittest discover -s tests -v
npm run test:model
```

Frontend data tests require Node.js TypeScript stripping support, available from 22.6 onward; Node.js 22.12+ also satisfies the editor's build requirement.

For browser tests, first start `npm run dev` in another terminal, then run:

```sh
npm run test:browser
```

On Windows, the test configuration uses Google Chrome from its default installation directory when available. Otherwise, run `npx playwright install chromium`, or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed browser executable. Set `KNOT_URL` to test a different running editor URL.

Tests cover workflow validation, task ownership, planner repairs, requirements extraction, runtime scheduling, review gates, local workspaces, retries, monitoring, usage accounting, storage, and browser interactions. Model responses in automated tests use fixtures or local test servers. These checks do not establish current provider availability or the quality of a real model's output. Dated results, live API checks, skips, and unresolved validation limits are recorded in [Verification history](docs/VERIFICATION.md).

### Reproduce the demo

To generate the current example ZIP without executing it:

```sh
python -m backend.export_example
```

To export, extract, run the mock example, verify that final files are absent before review, and **explicitly simulate approval** for development verification:

```sh
python scripts/verify_demo.py
```

The verification script saves outputs and a summary with the ZIP's SHA-256 under `artifacts/`. It is not included in downloaded user workspaces and does not represent approval by an authenticated person.

To walk through the sample manually, extract the ZIP into a new directory and run:

```sh
python run.py --mode mock
```

The sample pauses at review with exit code 2. Inspect the saved drafts, then explicitly approve its configured review:

```sh
python run.py --mode mock --resume --review review --decision approve --reviewer member-3
```

Use `--decision reject` to reject it. Other workflows may have different review node and member IDs; the runner prints the appropriate resume command. Resume in the original mode, and use a fresh extracted folder for a new run.

### Git hygiene

Keep credential values empty in `.env.example` and actual keys in ignored local configuration. Dependencies, builds, run results, and `artifacts/` are excluded by `.gitignore`; `.gitattributes` standardizes line endings.

Enable the repository's commit hooks in each clone and scan staged files before committing:

```sh
git config core.hooksPath .githooks
npm run check:secrets
```

### Repository layout

| Path                             | Contents                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------- |
| `src/`                           | React, TypeScript, and React Flow editor, project library, requirements UI, and cost ledger |
| `server.py`, `backend/`          | HTTP API, document extraction, planning, connection settings, and ZIP assembly              |
| `runtime/`, `run.py`             | Execution engine, provider adapters, local working copies, and CLI                          |
| `knot.py`, `knot.cmd`, `knot.sh` | Run, monitor, and status entry points                                                       |
| `api/index.py`, `vercel.json`    | Hosted API entry point and Vercel configuration                                             |
| `examples/team-research.json`    | Editable sample workflow                                                                    |
| `tests/`                         | Python, frontend data, and browser tests                                                    |
| `docs/SCHEMA.md`                 | Workflow fields and execution semantics                                                     |
| `docs/REQUIREMENTS.md`           | Requirements intake and task ownership guide                                                |
| `docs/BILLING.md`                | Usage accounting, cost confirmation, and member splitting                                   |
| `docs/VERIFICATION.md`           | Historical validation evidence and known gaps                                               |

The linked detailed guides currently contain Chinese documentation.

## Current limitations

- Execution supports a single computer and acyclic workflows. Cross-computer scheduling, loops, and real-time collaboration are not implemented.
- Local execution depends on the installed CLI, its authentication, available tools, and command permissions. Separate working copies isolate file changes but are not operating-system sandboxes.
- Direct API mode has only the limited file tools described above. It cannot execute arbitrary code or render project files that require external tools by itself.
- Human review is an explicit local decision, without enterprise identity verification. Task acceptance criteria guide the model and reviewer; they do not automatically prove correctness.
- Requirements import handles text PDFs, TXT, and Markdown without OCR. The exported runner receives extracted UTF-8 resources rather than parsing the original PDF at runtime.
- Natural-language edits to selected parts of an existing workflow are not implemented. Generated drafts remain fully editable on the canvas.
- Browser storage has capacity and device limits. Back up workflow JSON and the separate cost ledger, even when optional cloud saves are configured.
