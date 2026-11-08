# KNOT shared implementation contract

Schema version: `1.0`. All interfaces use the same JSON document.

```ts
type Workflow = {
  schema_version: '1.0';
  project: { id: string; name: string; goal: string; deliverable: string; members: {id:string;name:string;skills:string}[] };
  agents: {id:string;name:string;role:string;system_prompt:string;provider:'openai'|'anthropic';model:string;credential_ref:string;base_url?:string;tools:string[]}[];
  nodes: {id:string;type:'start'|'agent_task'|'shared_resource'|'parallel'|'condition'|'human_review'|'output';label:string;position:{x:number;y:number};config:Record<string,any>}[];
  edges: {id:string;source:string;target:string;source_port:string;target_port:string;kind:'control'|'data'}[];
  resources: {id:string;name:string;path:string;description:string;example:boolean;content?:string}[];
  limits: {max_concurrency:number;timeout_seconds:number;max_retries:number;max_tool_rounds:number};
  viewport: {x:number;y:number;zoom:number};
  design_notes: string[];
};
```

Config fields:
- all nodes: `join_rule: 'all_selected' | 'all_success'` (default all_selected). Wait for ALL control and data dependencies to settle. all_selected requires at least one activated control input, and accepts skipped inputs; all_success requires every control input active/successful. A node with only data dependencies waits for them; validate control reachability separately. Any failed dependency blocks descendants. Skipped branch data is absent, never an unending wait.
- start: no config.
- shared_resource: `resource_ids: string[]`. Reads only declared resources; paths restricted to inputs/. It returns resource contents. Resources with inline content are bundled. Missing external inputs produce warnings on export and clear runtime preflight errors.
- parallel: starts independent outgoing control branches, no special config.
- agent_task: `agent_id`, `owner_id`, `instructions`, `acceptance`, `output_format: 'markdown'|'json'|'csv'`, `permissions: {read:string[];write:string[]}`, `tools:string[]`, `mock_result?: {content:string;data:any}`, `mock_delay_ms?:number`. Tools are intersection of agent and task permissions. Input results are ONLY from incoming data edges. Explicit system prompt + task instructions + project goal + these inputs form independent per-task model messages. No transcript shared between agents.
- condition: `source_node`, `field` (dot path, e.g. data.approved), `operator: 'eq'|'neq'|'gt'|'contains'`, `value:any`. source_node requires incoming data edge. Outgoing control port MUST be `true` or `false`.
- human_review: `owner_id`, `instructions`. CLI pauses in waiting_review, saves run state, then requires exact human approve/reject via resume command. Cannot autoapprove. Rejection fails/blocks descendants.
- output: `mappings: {source_node:string;filename:string;format:'markdown'|'json'|'csv'}[]`. Each source requires incoming data edge. filenames relative to results/; writes are final delivery. Internal task state remains in logs/, so report.md does not appear before review.

Ports: ordinary control `out` -> `in`; condition `true`/`false` -> `in`; data `data-out` -> `data-in`. Connections do not imply data access. Both dependency kinds participate in DAG cycle checks. Control edges must make ALL nodes reachable from exactly one Start. No incoming edges to Start. Output has no control output. All nodes have optional data output. Output mappings can point to an ancestor task via direct data edge while the control path goes through Human Review.

Direct API (`--mode real`) tools: `read_text`, `read_csv`, `summarize_csv`, `write_file`. No shell, code execution, web browsing in this legacy path. Reads only inputs/ or results/ with task grants; writes only results/ with task grants; enforce resolved path containment and symlink protection. Logs/state managed separately by executor.

Local coding (`--mode local`, default): one `knot.json` configuration chooses `backend: 'codex'|'claude'|'opencode'|null`, optional shared `model` (empty means CLI default for Codex/Claude), `task_timeout_seconds` (default 1800), and `schema_version: '1.0'`. Codex/Claude roles inherit the shared model. OpenCode requires an empty shared model and resolves each task's model and credential through its owner member's connection; per-agent API credentials do not override this route. Each task starts an independent coding CLI session in its own working copy; explicit data dependencies carry source changes and structured results, while control-only edges do not grant them. Conflicting changes fail explicitly. Output nodes publish combined code under `results/project/` after the required control path and Human Review gates. Separate working copies are not an OS sandbox; CLI permissions govern command execution.

Local failed-task recovery is explicit (`--retry-failed`). It requires an unchanged workflow and execution configuration, a terminal failed run with only agent-task failures, and no rejected human review or running tasks. The saved state is backed up; successful tasks and their results stay intact. Only failed tasks and their blocked descendants return to pending. A failed task may reuse its own draft in a new attempt directory; completion still requires a new worker result and normal artifact collection. Existing drafts are neither promoted to success automatically nor overwritten. Method failures resolved by permitted alternatives are reported as limitations when the assigned deliverables and acceptance checks are met; an explicitly required method or outstanding acceptance check remains mandatory.

Python modules: `runtime/validation.py` exposes `validate_workflow(workflow, mode='mock') -> list[dict]` issues `{severity:'error'|'warning',code,message,node_id?:str}`; `runtime/engine.py` exposes CLI via `run.py` and reusable engine (agent documents its API). Provider adapter in `runtime/providers.py`. Python 3.10+ stdlib preferred.

HTTP backend `server.py`, port 8000, loopback only. Routes:
- GET /api/health -> {ok:true,planner_credentials:{OPENAI_API_KEY:boolean,ANTHROPIC_API_KEY:boolean,DEEPSEEK_API_KEY:boolean,...},default_planner:connection|null,credential_export_allowed:boolean}. Only configuration and boolean availability, never credential values. Personal credential export is available only for a non-hosted loopback server and loopback client/Host.
- POST /api/credentials body {credential_ref,key} -> {credentials:{[ref]:boolean}}. Local-only credential configuration: atomically save in ignored .env.local, activate in the backend, never return key values. Temporary-file permissions are owner-only on POSIX; Windows uses the directory's inherited ACL.
- POST /api/connection/test body {connection:{provider,model,credential_ref,base_url}} -> {ok,model,message}. Generic test prompt only; output capped at 16 tokens for compatible/Anthropic services and 512 completion tokens (including reasoning) for the official OpenAI API. Success requires a complete nonempty text response; preserve safe provider error diagnostics.
- GET /api/template -> Workflow
- POST /api/validate body {workflow,mode} -> {issues}
- POST /api/export body {workflow,execution?:{backend,model?,task_timeout_seconds?,schema_version?},include_member_credentials?:boolean} -> application/zip. Execution settings are normalized, whitelisted, and secret-checked separately. Fatal invalid graph rejects 400; missing per-agent API models do not block local coding export. Missing execution selection is deferred to the local launcher, never silently selects mock. The optional boolean defaults to false. When true, only local non-hosted OpenCode export is allowed; read only actual task owners' saved keys from .env.local and put them in a separate .env inside knot-personal-workspace.zip. Missing saved keys reject export before download; never fall back to global/server environment secrets. Responses are no-store. The UI labels the package as containing plaintext credentials and offers a key-free export.
- POST /api/plan body {project,resources,planner:{provider,model,credential_ref,base_url?}} -> {workflow}; server env credentials only, at most 2 repair attempts, no mock fallback. Real planner schema validation and capability restrictions.
- Backend serves dist/ in production. Vite proxies /api to localhost:8000.

Exporter in `backend/bundle.py`, function `build_bundle(workflow, execution=None, *, member_credentials=None)->bytes`. Bundle root includes workflow.json, knot.json, run.py, runtime/, prompts/, tasks/, inputs/, empty workspace/, requirements.txt (stdlib comment allowed), .env.example, .gitignore, start.bat, start.sh, START-HERE.md, README.md, AGENTS.md, and CLAUDE.md. Task and prompt files are readable references; workflow.json remains authoritative. Startup with no arguments enters interactive local execution; explicit mock/real arguments preserve legacy modes. No external KNOT backend dependency. By default the bundle has no secrets. An explicitly supplied credential mapping must exactly match OpenCode task-owner references, and is written only to .env; the blank .env.example remains and .gitignore excludes credentials. Personal packages are labeled private in README and START-HERE. The builder itself does not read local secret files. Codex/Claude CLI and supported authentication must exist on the execution machine. Export checks still disallow credential literals in the workflow and path escape. Demo `examples/team-research.json` contains start, shared resource, parallel, 2 task branches, synthesis task, human review, output, report.md and summary.csv mappings. Data edges must match runtime inputs.

Workflow JSON and browser persistence store credential REFERENCES, never secrets. A separate password input sends an explicitly entered key only to the local credentials endpoint, then clears it. DeepSeek presets use provider openai with its own base_url and DEEPSEEK_API_KEY reference. Planner models remain configured separately from agents. Nodes and edges preserve the entire schema, undo/redo and local autosave. Two creation routes lead to the same canvas. Template distinctly labeled.
