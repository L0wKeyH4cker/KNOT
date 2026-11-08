import { useState } from 'react';
import { Plus, Trash2, Bot, ShieldCheck, Users, FolderOpen, ArrowUpRight } from 'lucide-react';
import ConnectionSettings from './ConnectionSettings';
import { Field, CheckList } from './Inspector';
import { newAgent, TOOLS, uid } from './model';
import { newMemberConnection } from './owner-connections';
import type { Workflow, Agent, Member, Resource } from './model';
export function AgentsSettings({
  wf,
  change,
  credentials,
  onCredentialsChange,
}: {
  wf: Workflow;
  change: (w: Workflow) => void;
  credentials: Record<string, boolean>;
  onCredentialsChange: (credentials: Record<string, boolean>) => void;
}) {
  const [active, setActive] = useState(wf.agents[0]?.id || '');
  const a = wf.agents.find((a) => a.id === active);
  const update = (patch: Partial<Agent>) =>
    change({ ...wf, agents: wf.agents.map((x) => (x.id === active ? { ...x, ...patch } : x)) });
  return (
    <div className="agents-layout">
      <div className="agent-list">
        <div className="section-label">
          YOUR AGENTS <span>{wf.agents.length}</span>
        </div>
        {wf.agents.map((x) => (
          <button
            key={x.id}
            className={`agent-choice ${active === x.id ? 'active' : ''}`}
            onClick={() => setActive(x.id)}
          >
            <span className="agent-icon">
              <Bot size={19} />
            </span>
            <span>
              <strong>{x.name}</strong>
            </span>
          </button>
        ))}
        <button
          className="secondary full"
          onClick={() => {
            const n = newAgent();
            change({ ...wf, agents: [...wf.agents, n] });
            setActive(n.id);
          }}
        >
          <Plus size={16} />
          New agent
        </button>
      </div>
      <div className="agent-editor">
        {a ? (
          <>
            <div className="row between">
              <h3>Agent configuration</h3>
              <button
                className="icon-button danger"
                title="Delete agent"
                onClick={() => {
                  change({ ...wf, agents: wf.agents.filter((x) => x.id !== active) });
                  setActive(wf.agents.find((x) => x.id !== active)?.id || '');
                }}
              >
                <Trash2 size={17} />
              </button>
            </div>
            <div className="form-grid">
              <Field label="Name">
                <input value={a.name} onChange={(e) => update({ name: e.target.value })} />
              </Field>
              <Field label="Role">
                <input value={a.role} onChange={(e) => update({ role: e.target.value })} />
              </Field>
            </div>
            <Field label="System prompt">
              <textarea
                rows={5}
                value={a.system_prompt}
                onChange={(e) => update({ system_prompt: e.target.value })}
              />
            </Field>
            <p className="muted">
              OpenCode uses the task owner's connection in Project settings → Team members. The
              connection below is used by direct API mode.
            </p>
            <ConnectionSettings
              key={a.id}
              connection={a}
              onChange={update}
              credentials={credentials}
              onCredentialsChange={onCredentialsChange}
            />
            <Field label="Allowed tools">
              <CheckList
                values={TOOLS}
                selected={a.tools}
                onChange={(tools) => update({ tools })}
              />
            </Field>
            <div className="note">
              <ShieldCheck size={16} />
              Enable tools on both the agent and its assigned tasks.
            </div>
          </>
        ) : (
          <div className="empty-panel">
            <Bot size={40} />
            <h3>Add your first agent</h3>
            <p>Assign it to tasks on your canvas.</p>
          </div>
        )}
      </div>
    </div>
  );
}
export function ProjectSettings({
  wf,
  change,
  credentials,
  onCredentialsChange,
}: {
  wf: Workflow;
  change: (w: Workflow) => void;
  credentials: Record<string, boolean>;
  onCredentialsChange: (credentials: Record<string, boolean>) => void;
}) {
  const [activeMember, setActiveMember] = useState('');
  const updateMember = (id: string, patch: Partial<Member>) =>
    change({
      ...wf,
      project: {
        ...wf.project,
        members: wf.project.members.map((member) =>
          member.id === id ? { ...member, ...patch } : member,
        ),
      },
    });
  const updateResource = (id: string, p: Partial<Resource>) =>
    change({ ...wf, resources: wf.resources.map((r) => (r.id === id ? { ...r, ...p } : r)) });
  return (
    <div className="project-settings">
      <div className="form-grid">
        <Field label="Project name">
          <input
            value={wf.project.name}
            onChange={(e) => change({ ...wf, project: { ...wf.project, name: e.target.value } })}
          />
        </Field>
        <Field label="Final deliverable">
          <input
            value={wf.project.deliverable}
            onChange={(e) =>
              change({ ...wf, project: { ...wf.project, deliverable: e.target.value } })
            }
          />
        </Field>
      </div>
      <Field label="Project goal">
        <textarea
          rows={3}
          value={wf.project.goal}
          onChange={(e) => change({ ...wf, project: { ...wf.project, goal: e.target.value } })}
        />
      </Field>
      <div className="section-label">
        <Users size={16} />
        Team members
      </div>
      <p className="muted">
        Choose OpenCode when exporting to run each task with its owner's model and API key. Keys
        must be saved with Save on this device. Local personal exports can include the saved keys so
        the extracted package is ready to run.
      </p>
      {wf.project.members.map((m, i) => (
        <article className="member-settings" key={m.id} aria-label={`Member ${i + 1} settings`}>
          <div className="member-row">
            <span className={`avatar avatar-${i % 4}`}>{m.name.slice(0, 1)}</span>
            <input
              aria-label={`Member ${i + 1} name`}
              value={m.name}
              onChange={(e) =>
                change({
                  ...wf,
                  project: {
                    ...wf.project,
                    members: wf.project.members.map((x) =>
                      x.id === m.id ? { ...x, name: e.target.value } : x,
                    ),
                  },
                })
              }
            />
            <input
              aria-label={`Member ${i + 1} skills`}
              placeholder="Skills (optional)"
              value={m.skills}
              onChange={(e) =>
                change({
                  ...wf,
                  project: {
                    ...wf.project,
                    members: wf.project.members.map((x) =>
                      x.id === m.id ? { ...x, skills: e.target.value } : x,
                    ),
                  },
                })
              }
            />
            <button
              className="icon-button danger"
              title="Remove member"
              disabled={wf.project.members.length === 1}
              onClick={() =>
                change({
                  ...wf,
                  project: {
                    ...wf.project,
                    members: wf.project.members.filter((x) => x.id !== m.id),
                  },
                })
              }
            >
              <Trash2 size={15} />
            </button>
          </div>
          <div className="member-connection-summary">
            <span>{m.connection?.model || 'No OpenCode model configured'}</span>
            <button
              className="text-button"
              aria-label={`Configure connection for ${m.name}`}
              aria-expanded={activeMember === m.id}
              onClick={() => {
                if (!m.connection)
                  updateMember(m.id, { connection: newMemberConnection(wf.project.id, m.id) });
                setActiveMember(activeMember === m.id ? '' : m.id);
              }}
            >
              {activeMember === m.id ? 'Hide connection' : 'Configure connection'}
            </button>
          </div>
          {activeMember === m.id && m.connection && (
            <ConnectionSettings
              key={m.id}
              connection={m.connection}
              onChange={(connection) => updateMember(m.id, { connection })}
              credentials={credentials}
              onCredentialsChange={onCredentialsChange}
              memberConnection
            />
          )}
        </article>
      ))}
      <button
        className="text-button"
        onClick={() =>
          change({
            ...wf,
            project: {
              ...wf.project,
              members: [
                ...wf.project.members,
                {
                  id: uid('member'),
                  name: `Member ${String.fromCharCode(65 + wf.project.members.length)}`,
                  skills: '',
                },
              ],
            },
          })
        }
      >
        <Plus size={14} />
        Add member
      </button>
      <div className="section-label">
        <FolderOpen size={16} />
        Input resources
      </div>
      <p className="muted">
        Content is included in the ZIP; leave it blank to add the file before running.
      </p>
      {wf.resources.map((r) => (
        <div className="resource-editor" key={r.id}>
          <div className="row">
            <input
              aria-label="Resource name"
              value={r.name}
              placeholder="Resource name"
              onChange={(e) => updateResource(r.id, { name: e.target.value })}
            />
            <button
              className="icon-button danger"
              title="Remove resource"
              onClick={() =>
                change({ ...wf, resources: wf.resources.filter((x) => x.id !== r.id) })
              }
            >
              <Trash2 size={15} />
            </button>
          </div>
          <Field label="File path">
            <input
              value={r.path}
              placeholder="inputs/brief.txt"
              onChange={(e) => updateResource(r.id, { path: e.target.value })}
            />
          </Field>
          <Field label="Description">
            <input
              value={r.description}
              onChange={(e) => updateResource(r.id, { description: e.target.value })}
            />
          </Field>
          <Field label="Text or CSV content (optional)">
            <textarea
              rows={3}
              value={r.content || ''}
              onChange={(e) => updateResource(r.id, { content: e.target.value || undefined })}
            />
          </Field>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={r.example}
              onChange={(e) => updateResource(r.id, { example: e.target.checked })}
            />
            This is example data
          </label>
        </div>
      ))}
      <button
        className="secondary"
        onClick={() =>
          change({
            ...wf,
            resources: [
              ...wf.resources,
              {
                id: uid('resource'),
                name: 'New resource',
                path: 'inputs/resource.txt',
                description: '',
                example: false,
              },
            ],
          })
        }
      >
        <Plus size={16} />
        Add resource
      </button>
      <div className="section-label">Run limits</div>
      <div className="form-grid">
        {Object.entries(wf.limits).map(([k, v]) => (
          <Field key={k} label={k.replaceAll('_', ' ')}>
            <input
              type="number"
              min={k === 'max_retries' ? 0 : 1}
              max={
                k === 'timeout_seconds'
                  ? 3600
                  : k === 'max_concurrency'
                    ? 16
                    : k === 'max_retries'
                      ? 5
                      : 20
              }
              value={v}
              onChange={(e) =>
                change({ ...wf, limits: { ...wf.limits, [k]: Number(e.target.value) } })
              }
            />
          </Field>
        ))}
      </div>
    </div>
  );
}
export type Planner = {
  provider: 'openai' | 'anthropic';
  model: string;
  credential_ref: string;
  base_url: string;
};
export function PlannerSettings({
  planner,
  setPlanner,
  credentials,
  onCredentialsChange,
  busy,
  generate,
  hasNodes,
  configurationOnly = false,
}: {
  planner: Planner;
  setPlanner: (p: Planner) => void;
  credentials: Record<string, boolean>;
  onCredentialsChange: (credentials: Record<string, boolean>) => void;
  busy: boolean;
  generate: () => void;
  hasNodes: boolean;
  configurationOnly?: boolean;
}) {
  return (
    <div className="planner-content">
      {!configurationOnly && (
        <div className="planner-hero">
          <h3>Generate a workflow</h3>
        </div>
      )}
      <ConnectionSettings
        planning
        connection={planner}
        onChange={setPlanner}
        credentials={credentials}
        onCredentialsChange={onCredentialsChange}
        disabled={busy}
      />
      {!configurationOnly && (
        <>
          <p className="muted">
            This model plans the workflow; task agents run it.{' '}
            {hasNodes ? 'Generating replaces this canvas; undo restores the previous version.' : ''}
          </p>
          <button
            className="primary full"
            disabled={busy || !planner.model.trim()}
            onClick={generate}
          >
            {busy ? 'Designing your workflow…' : 'Generate with AI'}
            <ArrowUpRight size={17} />
          </button>
        </>
      )}
    </div>
  );
}
