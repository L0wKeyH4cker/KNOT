export type NodeKind =
  'start' | 'agent_task' | 'shared_resource' | 'parallel' | 'condition' | 'human_review' | 'output';
export type Member = { id: string; name: string; skills: string };
export type Agent = {
  id: string;
  name: string;
  role: string;
  system_prompt: string;
  provider: 'openai' | 'anthropic';
  model: string;
  credential_ref: string;
  base_url?: string;
  tools: string[];
};
export type Resource = {
  id: string;
  name: string;
  path: string;
  description: string;
  example: boolean;
  content?: string;
};
export type Mapping = {
  source_node: string;
  filename: string;
  format: 'markdown' | 'json' | 'csv';
};
export type Config = {
  join_rule?: 'all_selected' | 'all_success';
  resource_ids?: string[];
  agent_id?: string;
  owner_id?: string;
  requirement_task_indexes?: number[];
  instructions?: string;
  acceptance?: string;
  output_format?: 'markdown' | 'json' | 'csv';
  permissions?: { read: string[]; write: string[] };
  tools?: string[];
  mock_result?: { content: string; data: unknown };
  mock_delay_ms?: number;
  source_node?: string;
  field?: string;
  operator?: 'eq' | 'neq' | 'gt' | 'contains';
  value?: unknown;
  mappings?: Mapping[];
};
export type Block = {
  id: string;
  type: NodeKind;
  label: string;
  position: { x: number; y: number };
  config: Config;
};
export type Link = {
  id: string;
  source: string;
  target: string;
  source_port: string;
  target_port: string;
  kind: 'control' | 'data';
};
export type Workflow = {
  schema_version: '1.0';
  project: { id: string; name: string; goal: string; deliverable: string; members: Member[] };
  agents: Agent[];
  nodes: Block[];
  edges: Link[];
  resources: Resource[];
  limits: {
    max_concurrency: number;
    timeout_seconds: number;
    max_retries: number;
    max_tool_rounds: number;
  };
  viewport: { x: number; y: number; zoom: number };
  design_notes: string[];
};
export type Issue = {
  severity: 'error' | 'warning';
  code: string;
  message: string;
  node_id?: string;
};
export const TOOLS = ['read_text', 'read_csv', 'summarize_csv', 'write_file'];
export const KINDS: Record<
  NodeKind,
  { name: string; description: string; color: string; tag: string }
> = {
  start: {
    name: 'Start',
    description: 'Where your workflow begins',
    color: '#4965b0',
    tag: 'TRIGGER',
  },
  agent_task: {
    name: 'Agent Task',
    description: 'Give an AI agent a job',
    color: '#5974b3',
    tag: 'ACTION',
  },
  shared_resource: {
    name: 'Shared Resource',
    description: 'Bring your inputs together',
    color: '#b18a43',
    tag: 'CONTEXT',
  },
  parallel: {
    name: 'Parallel',
    description: 'Let tasks work side by side',
    color: '#9970b5',
    tag: 'FLOW',
  },
  condition: {
    name: 'Condition',
    description: 'Choose a path with a rule',
    color: '#c18a39',
    tag: 'LOGIC',
  },
  human_review: {
    name: 'Human Review',
    description: 'Keep your team in the loop',
    color: '#c17c65',
    tag: 'REVIEW',
  },
  output: {
    name: 'Output',
    description: 'Turn work into deliverables',
    color: '#5876bd',
    tag: 'DELIVERY',
  },
};
export const uid = (prefix = 'id') => `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
export function emptyWorkflow(): Workflow {
  return {
    schema_version: '1.0',
    project: {
      id: uid('project'),
      name: 'Untitled project',
      goal: '',
      deliverable: '',
      members: [{ id: 'project-owner', name: 'Project owner', skills: '' }],
    },
    agents: [],
    nodes: [],
    edges: [],
    resources: [],
    limits: { max_concurrency: 3, timeout_seconds: 60, max_retries: 1, max_tool_rounds: 4 },
    viewport: { x: 60, y: 100, zoom: 1 },
    design_notes: [],
  };
}
export function newAgent(): Agent {
  return {
    id: uid('agent'),
    name: 'New agent',
    role: 'Research assistant',
    system_prompt:
      'Complete the assigned task using only the provided context and permitted tools. State uncertainty and do not invent sources.',
    provider: 'openai',
    model: '',
    credential_ref: 'OPENAI_API_KEY',
    tools: [],
  };
}
export function newBlock(type: NodeKind, position: Block['position'], wf: Workflow): Block {
  let config: Config = { join_rule: 'all_selected' };
  if (type === 'agent_task')
    config = {
      ...config,
      agent_id: wf.agents[0]?.id || '',
      owner_id: wf.project.members[0]?.id || '',
      instructions: '',
      acceptance: '',
      output_format: 'markdown',
      permissions: { read: [], write: [] },
      tools: [],
    };
  if (type === 'shared_resource') config.resource_ids = [];
  if (type === 'condition')
    config = { ...config, source_node: '', field: 'data.approved', operator: 'eq', value: true };
  if (type === 'human_review')
    config = {
      ...config,
      owner_id: wf.project.members[0]?.id || '',
      instructions: 'Review the upstream work and approve it before delivery.',
    };
  if (type === 'output') config.mappings = [];
  return { id: uid(type), type, label: KINDS[type].name, position, config };
}
export function hasCycle(nodes: Block[], edges: Link[]): boolean {
  const visiting = new Set<string>(),
    done = new Set<string>();
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (done.has(id)) return false;
    visiting.add(id);
    for (const e of edges.filter((x) => x.source === id)) {
      if (visit(e.target)) return true;
    }
    visiting.delete(id);
    done.add(id);
    return false;
  };
  return nodes.some((n) => visit(n.id));
}
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/;
const ENV_PATTERN = /^[A-Z][A-Z0-9_]{0,99}$/;
const SECRET_PATTERN = /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b|\bBearer\s+[A-Za-z0-9._-]{20,}/i;
const SECRET_FIELDS = new Set([
  'apikey',
  'accesstoken',
  'authorization',
  'secret',
  'clientsecret',
  'password',
  'privatekey',
]);

/** Run before local persistence/export as well as import. Keys belong only in the runtime environment. */
export function assertSafeWorkflow(value: unknown): void {
  const seen = new WeakSet<object>();
  const visit = (entry: unknown): void => {
    if (typeof entry === 'string' && SECRET_PATTERN.test(entry))
      throw Error(
        'A possible API key was found. Remove it and use an environment-variable credential reference.',
      );
    if (!entry || typeof entry !== 'object') return;
    if (seen.has(entry)) throw Error('Workflow data must not contain circular object references.');
    seen.add(entry);
    for (const [key, child] of Object.entries(entry)) {
      visit(key);
      if (SECRET_FIELDS.has(key.toLowerCase().replace(/[_-]/g, '')))
        throw Error(
          `Secret field "${key}" cannot be saved in a workflow. Use credential_ref instead.`,
        );
      if (
        key === 'credential_ref' &&
        typeof child === 'string' &&
        child !== '' &&
        !ENV_PATTERN.test(child)
      )
        throw Error(
          'Credential references must be uppercase environment-variable names, never API keys.',
        );
      visit(child);
    }
    seen.delete(entry);
  };
  visit(value);
}

/** Strict shape checking; incomplete task/model settings remain editable and are checked before export. */
export function parseWorkflow(value: unknown): Workflow {
  assertSafeWorkflow(value);
  const object = (v: unknown, name: string): Record<string, unknown> => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error(`${name} must be an object.`);
    return v as Record<string, unknown>;
  };
  const text = (v: unknown, name: string) => {
    if (typeof v !== 'string') throw Error(`${name} must be text.`);
  };
  const finite = (v: unknown, name: string) => {
    if (typeof v !== 'number' || !Number.isFinite(v))
      throw Error(`${name} must be a finite number.`);
  };
  const list = (v: unknown, name: string): unknown[] => {
    if (!Array.isArray(v)) throw Error(`${name} must be a list.`);
    return v;
  };
  const texts = (v: unknown, name: string) => list(v, name).forEach((x) => text(x, name));
  const entries = (v: unknown, name: string): Record<string, unknown>[] => {
    const ids = new Set<string>();
    return list(v, name).map((entry) => {
      const item = object(entry, name);
      if (typeof item.id !== 'string' || !ID_PATTERN.test(item.id))
        throw Error(`${name} needs a valid ID using letters, numbers, underscores or dashes.`);
      if (ids.has(item.id)) throw Error(`Duplicate ${name} ID: ${item.id}`);
      ids.add(item.id);
      return item;
    });
  };
  const raw = object(value, 'Workflow');
  if (raw.schema_version !== '1.0')
    throw Error('Unsupported workflow version. Expected schema_version 1.0.');
  const project = object(raw.project, 'Project');
  for (const key of ['id', 'name', 'goal', 'deliverable']) text(project[key], `Project ${key}`);
  entries(project.members, 'Member').forEach((m) => {
    text(m.name, 'Member name');
    text(m.skills, 'Member skills');
  });
  entries(raw.agents, 'Agent').forEach((a) => {
    for (const key of ['name', 'role', 'system_prompt', 'model', 'credential_ref'])
      text(a[key], `Agent ${key}`);
    if (a.provider !== 'openai' && a.provider !== 'anthropic')
      throw Error('Unsupported agent provider.');
    texts(a.tools, 'Agent tools');
    if (a.base_url !== undefined) text(a.base_url, 'Agent base URL');
  });
  entries(raw.resources, 'Resource').forEach((r) => {
    for (const key of ['name', 'path', 'description']) text(r[key], `Resource ${key}`);
    if (typeof r.example !== 'boolean') throw Error('Resource example flag must be true or false.');
    if (r.content !== undefined) text(r.content, 'Resource content');
  });
  const nodes = entries(raw.nodes, 'Block');
  nodes.forEach((n) => {
    if (typeof n.type !== 'string' || !Object.hasOwn(KINDS, n.type))
      throw Error('Unsupported block type.');
    text(n.label, 'Block name');
    const position = object(n.position, 'Block position');
    finite(position.x, 'Block x');
    finite(position.y, 'Block y');
    const c = object(n.config, 'Block configuration');
    if (
      c.requirement_task_indexes !== undefined &&
      list(c.requirement_task_indexes, 'Requirement task indexes').some(
        (index) => typeof index !== 'number' || !Number.isInteger(index) || index < 1,
      )
    )
      throw Error('Requirement task indexes must be positive whole numbers.');
    for (const key of [
      'agent_id',
      'owner_id',
      'instructions',
      'acceptance',
      'source_node',
      'field',
    ])
      if (c[key] !== undefined) text(c[key], `Block ${key}`);
    if (
      c.join_rule !== undefined &&
      (typeof c.join_rule !== 'string' || !['all_selected', 'all_success'].includes(c.join_rule))
    )
      throw Error('Unsupported join rule.');
    if (
      c.output_format !== undefined &&
      (typeof c.output_format !== 'string' ||
        !['markdown', 'json', 'csv'].includes(c.output_format))
    )
      throw Error('Unsupported task output format.');
    if (
      c.operator !== undefined &&
      (typeof c.operator !== 'string' || !['eq', 'neq', 'gt', 'contains'].includes(c.operator))
    )
      throw Error('Unsupported condition operator.');
    for (const key of ['tools', 'resource_ids'])
      if (c[key] !== undefined) texts(c[key], `Block ${key}`);
    if (c.permissions !== undefined) {
      const p = object(c.permissions, 'Permissions');
      texts(p.read, 'Read permissions');
      texts(p.write, 'Write permissions');
    }
    if (c.mock_delay_ms !== undefined) finite(c.mock_delay_ms, 'Mock delay');
    if (c.mock_result !== undefined) {
      const result = object(c.mock_result, 'Mock result');
      text(result.content, 'Mock content');
    }
    if (c.mappings !== undefined)
      list(c.mappings, 'Output mappings').forEach((v) => {
        const m = object(v, 'Output mapping');
        text(m.source_node, 'Output source');
        text(m.filename, 'Output filename');
        if (typeof m.format !== 'string' || !['markdown', 'json', 'csv'].includes(m.format))
          throw Error('Unsupported output mapping format.');
      });
  });
  entries(raw.edges, 'Connection').forEach((e) => {
    for (const key of ['source', 'target', 'source_port', 'target_port'])
      text(e[key], `Connection ${key}`);
    const source = nodes.find((n) => n.id === e.source),
      target = nodes.find((n) => n.id === e.target);
    if (!source || !target) throw Error('A connection refers to a missing block.');
    if (target.type === 'start') throw Error('Start cannot have an incoming connection.');
    if (e.kind === 'data') {
      if (e.source_port !== 'data-out' || e.target_port !== 'data-in')
        throw Error('A data connection must join data-out to data-in.');
    } else if (e.kind === 'control') {
      const ports = source.type === 'condition' ? ['true', 'false'] : ['out'];
      if (
        source.type === 'output' ||
        !ports.includes(String(e.source_port)) ||
        e.target_port !== 'in'
      )
        throw Error('An execution connection uses incompatible ports.');
    } else throw Error('A connection must be execution or data.');
  });
  const limits = object(raw.limits, 'Runtime limits');
  for (const key of ['max_concurrency', 'timeout_seconds', 'max_retries', 'max_tool_rounds']) {
    finite(limits[key], key);
    if (!Number.isInteger(limits[key])) throw Error(`${key} must be a whole number.`);
  }
  const viewport = object(raw.viewport, 'Canvas viewport');
  for (const key of ['x', 'y', 'zoom']) finite(viewport[key], `Viewport ${key}`);
  if ((viewport.zoom as number) <= 0) throw Error('Viewport zoom must be positive.');
  texts(raw.design_notes, 'Design notes');
  const w = value as Workflow;
  if (hasCycle(w.nodes, w.edges))
    throw Error('This workflow contains a cycle. Only acyclic workflows can be imported.');
  return w;
}
export function localIssues(w: Workflow): Issue[] {
  const issues: Issue[] = [];
  const add = (
    code: string,
    message: string,
    node_id?: string,
    severity: 'error' | 'warning' = 'error',
  ) => issues.push({ code, message, node_id, severity });
  if (!w.project.goal.trim()) add('project_goal', 'Add your project goal.');
  if (w.nodes.filter((n) => n.type === 'start').length !== 1)
    add('start', 'Add exactly one Start block.');
  if (!w.nodes.some((n) => n.type === 'output')) add('output', 'Add an Output block.');
  if (hasCycle(w.nodes, w.edges))
    add('cycle', 'Connections form a cycle. Remove a connection to continue.');
  w.nodes.forEach((n) => {
    if (n.type !== 'start' && !w.edges.some((e) => e.target === n.id && e.kind === 'control'))
      add('disconnected', `${n.label}: connect an execution input.`, n.id);
    if (n.type === 'agent_task') {
      if (!n.config.instructions?.trim())
        add('instructions', `${n.label}: add task instructions.`, n.id);
      if (!w.agents.some((a) => a.id === n.config.agent_id))
        add('agent', `${n.label}: choose an agent.`, n.id);
      if (!n.config.owner_id) add('owner', `${n.label}: choose a human owner.`, n.id);
    }
    if (n.type === 'output' && !n.config.mappings?.length)
      add('mappings', `${n.label}: add a delivery file.`, n.id);
    if (n.type === 'human_review' && !n.config.owner_id)
      add('review_owner', `${n.label}: choose a reviewer.`, n.id);
  });
  w.agents.forEach((a) => {
    if (!a.model.trim())
      add(
        'model',
        `${a.name}: model is not configured; mock mode is available.`,
        undefined,
        'warning',
      );
  });
  return issues;
}
function apiErrorMessage(payload: unknown, status: number): string {
  const fallback = `Server error (${status})`;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return fallback;
  const error = payload as Record<string, unknown>;
  const message =
    [error.error, error.message].find(
      (value): value is string => typeof value === 'string' && Boolean(value.trim()),
    ) || fallback;
  const details: string[] = [];
  const seen = new Set<string>();
  if (Array.isArray(error.issues)) {
    for (const value of error.issues) {
      if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
      const issue = value as Record<string, unknown>;
      if (typeof issue.message !== 'string' || !issue.message.trim()) continue;
      const node = typeof issue.node_id === 'string' ? issue.node_id : '';
      const code = typeof issue.code === 'string' ? issue.code : '';
      const key = JSON.stringify([code, node, issue.message]);
      if (seen.has(key)) continue;
      seen.add(key);
      details.push(`- ${node ? `[${node}] ` : ''}${issue.message}`);
    }
  }
  return [message, ...details].join('\n');
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(
    `/api/${path}`,
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : {},
  );
  if (!res.ok) {
    let message = `Server error (${res.status})`;
    try {
      message = apiErrorMessage(await res.json(), res.status);
    } catch {}
    throw Error(message);
  }
  return res.json();
}
export function download(data: Blob, name: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(data);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
