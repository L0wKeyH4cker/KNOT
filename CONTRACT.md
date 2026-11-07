# TeamBlocks shared implementation contract

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

Supported tools: `read_text`, `read_csv`, `summarize_csv`, `write_file`. No shell, code execution, web browsing. Reads only inputs/ or results/ with task grants; writes only results/ with task grants; enforce resolved path containment and symlink protection. Logs/state managed separately by executor.

Python modules: `runtime/validation.py` exposes `validate_workflow(workflow, mode='mock') -> list[dict]` issues `{severity:'error'|'warning',code,message,node_id?:str}`; `runtime/engine.py` exposes CLI via `run.py` and reusable engine (agent documents its API). Provider adapter in `runtime/providers.py`. Python 3.10+ stdlib preferred.

HTTP backend `server.py`, port 8000, loopback only. Routes:
- GET /api/health -> {ok:true,planner_credentials:{OPENAI_API_KEY:boolean,ANTHROPIC_API_KEY:boolean}}
- GET /api/template -> Workflow
- POST /api/validate body {workflow,mode} -> {issues}
- POST /api/export body {workflow} -> application/zip; fatal invalid graph rejects 400; missing model/key WARN for mock export.
- POST /api/plan body {project,resources,planner:{provider,model,credential_ref,base_url?}} -> {workflow}; server env credentials only, at most 2 repair attempts, no mock fallback. Real planner schema validation and capability restrictions.
- Backend serves dist/ in production. Vite proxies /api to localhost:8000.

Exporter in `backend/bundle.py`, function `build_bundle(workflow)->bytes`. Bundle root includes workflow.json, run.py, runtime/, prompts/, inputs/, requirements.txt (stdlib comment allowed), .env.example, start.bat, start.sh, README.md. No secrets or external backend dependency. Export checks disallow credential literals and path escape. Demo `examples/team-research.json` contains start, shared resource, parallel, 2 task branches, synthesis task, human review, output, report.md and summary.csv mappings. Data edges must match runtime inputs.

Frontend only stores credential REFERENCES, never secrets. Planner models configured separately from agents. Nodes and edges preserve entire schema, undo/redo and local autosave. Two creation routes lead to same canvas. Template distinctly labeled.
