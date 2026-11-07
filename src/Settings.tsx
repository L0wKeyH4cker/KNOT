import { useState } from 'react';
import {
  Plus,
  Trash2,
  Bot,
  ShieldCheck,
  Users,
  FolderOpen,
  ArrowUpRight,
  KeyRound,
} from 'lucide-react';
import { Field, CheckList } from './Inspector';
import { newAgent, TOOLS, uid } from './model';
import type { Workflow, Agent, Resource } from './model';
export function AgentsSettings({ wf, change }: { wf: Workflow; change: (w: Workflow) => void }) {
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
              <small>{x.role}</small>
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
        <p className="muted small">
          Agents and people are separate. Reuse an agent across any number of tasks.
        </p>
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
            <div className="form-grid">
              <Field label="Provider">
                <select
                  value={a.provider}
                  onChange={(e) =>
                    update({
                      provider: e.target.value as Agent['provider'],
                      model: '',
                      credential_ref:
                        e.target.value === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY',
                      base_url: '',
                    })
                  }
                >
                  <option value="openai">OpenAI-compatible</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </Field>
              <Field
                label="Model name"
                hint="Use the exact API model ID from your provider, not the display name."
              >
                <input
                  value={a.model}
                  placeholder="Enter your provider's model ID"
                  onChange={(e) => update({ model: e.target.value })}
                />
              </Field>
            </div>
            <Field
              label="Credential reference"
              hint="Environment variable name only. Never paste an API key here."
            >
              <input
                value={a.credential_ref}
                pattern="[A-Z][A-Z0-9_]*"
                onChange={(e) => update({ credential_ref: e.target.value })}
              />
            </Field>
            <Field label="API base URL (optional)">
              <input
                value={a.base_url || ''}
                placeholder={
                  a.provider === 'openai'
                    ? 'https://api.openai.com/v1'
                    : 'https://api.anthropic.com/v1'
                }
                onChange={(e) => update({ base_url: e.target.value })}
              />
            </Field>
            <Field label="Allowed tools">
              <CheckList
                values={TOOLS}
                selected={a.tools}
                onChange={(tools) => update({ tools })}
              />
            </Field>
            <div className="note">
              <ShieldCheck size={16} />
              Tools also need permission on each task. Credentials are configured locally when you
              run the package.
            </div>
          </>
        ) : (
          <div className="empty-panel">
            <Bot size={40} />
            <h3>A role for every kind of work.</h3>
            <p>Create your first agent, then assign it to a task.</p>
          </div>
        )}
      </div>
    </div>
  );
}
export function ProjectSettings({ wf, change }: { wf: Workflow; change: (w: Workflow) => void }) {
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
      {wf.project.members.map((m, i) => (
        <div className="member-row" key={m.id}>
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
      <p className="muted small">
        Text entered here is included in the ZIP. Leave content empty for a file you will add
        locally before running.
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
  busy,
  generate,
  hasNodes,
  configurationOnly = false,
}: {
  planner: Planner;
  setPlanner: (p: Planner) => void;
  credentials: Record<string, boolean>;
  busy: boolean;
  generate: () => void;
  hasNodes: boolean;
  configurationOnly?: boolean;
}) {
  return (
    <div className="planner-content">
      {!configurationOnly && (
        <div className="planner-hero">
          <span className="ai-orbit">✦</span>
          <h3>A starting point, made for your team.</h3>
          <p>
            Turn your project brief into an editable workflow. You stay in charge of every block,
            connection, and permission.
          </p>
        </div>
      )}
      <div className="form-grid">
        <Field label="Planning provider">
          <select
            value={planner.provider}
            onChange={(e) =>
              setPlanner({
                ...planner,
                provider: e.target.value as Planner['provider'],
                model: '',
                credential_ref:
                  e.target.value === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY',
                base_url: '',
              })
            }
          >
            <option value="openai">OpenAI-compatible</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </Field>
        <Field
          label="Planning model"
          hint={
            planner.provider === 'openai'
              ? 'Use the API ID, e.g. gpt-6-luna. Display names such as GPT-6 Luna are not API IDs.'
              : 'Use the exact API model ID from your provider, not the display name.'
          }
        >
          <input
            placeholder="Your model ID"
            value={planner.model}
            onChange={(e) => setPlanner({ ...planner, model: e.target.value })}
          />
        </Field>
      </div>
      <Field
        label="Credential environment variable"
        hint="Set this on the local backend. Keys are never entered or stored in the browser."
      >
        <input
          placeholder="OPENAI_API_KEY"
          value={planner.credential_ref}
          onChange={(e) => setPlanner({ ...planner, credential_ref: e.target.value })}
        />
      </Field>
      <Field label="API base URL (optional)">
        <input
          value={planner.base_url}
          onChange={(e) => setPlanner({ ...planner, base_url: e.target.value })}
          placeholder="Default provider endpoint"
        />
      </Field>
      <div className={`credential-status ${credentials[planner.credential_ref] ? 'ready' : ''}`}>
        <KeyRound size={16} />
        {credentials[planner.credential_ref] === true
          ? 'Credential detected on local backend'
          : credentials[planner.credential_ref] === false
            ? 'No credential detected. Real AI generation is unavailable until configured.'
            : 'Credential status not checked for this reference. The backend will check it when you run analysis or generation.'}
      </div>
      {!configurationOnly && (
        <>
          <p className="muted small">
            The planning model is independent of execution agents.{' '}
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
