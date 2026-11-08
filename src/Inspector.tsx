import {
  Copy,
  Trash2,
  X,
  Plus,
  ArrowDown,
  ShieldCheck,
  UserRound,
  SlidersHorizontal,
} from 'lucide-react';
import { KINDS, TOOLS } from './model';
import type { Block, Workflow, Config, Mapping } from './model';
import { icons } from './BlockNode';
import { cloneElement, isValidElement, useId } from 'react';
export function Field({
  label,
  children,
  hint,
  error,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
  error?: string;
}) {
  const id = useId();
  const element = isValidElement<{
    id?: string;
    required?: boolean;
    'aria-label'?: string;
    'aria-describedby'?: string;
    'aria-invalid'?: boolean;
  }>(children)
    ? children
    : null;
  const description = [hint && id + '-hint', error && id + '-error'].filter(Boolean).join(' ');
  const control = element
    ? cloneElement(element, {
        id,
        'aria-label': element.props['aria-label'] || (element.props.required ? label : undefined),
        'aria-describedby': description || undefined,
        'aria-invalid': error ? true : undefined,
      })
    : children;
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {element?.props.required && (
          <span className="required-mark" aria-hidden="true">
            {' '}
            *
          </span>
        )}
      </label>
      {control}
      {hint && <small id={id + '-hint'}>{hint}</small>}
      {error && (
        <small className="field-error" id={id + '-error'}>
          {error}
        </small>
      )}
    </div>
  );
}
export function CheckList({
  values,
  selected,
  onChange,
}: {
  values: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="check-list">
      {values.map((t) => (
        <label key={t}>
          <input
            type="checkbox"
            checked={selected.includes(t)}
            onChange={(e) =>
              onChange(e.target.checked ? [...selected, t] : selected.filter((x) => x !== t))
            }
          />
          {t.replaceAll('_', ' ')}
        </label>
      ))}
    </div>
  );
}
export default function Inspector({
  node,
  wf,
  onChange,
  onClose,
  onDuplicate,
  onDelete,
  onAgents,
  onMembers,
  credentials,
}: {
  node: Block;
  wf: Workflow;
  onChange: (n: Block) => void;
  onClose: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onAgents: () => void;
  onMembers: () => void;
  credentials: Record<string, boolean>;
}) {
  const c = node.config,
    Icon = icons[node.type],
    set = (patch: Partial<Config>) => onChange({ ...node, config: { ...c, ...patch } });
  const dataSources = wf.edges
    .filter((e) => e.target === node.id && e.kind === 'data')
    .map((e) => wf.nodes.find((n) => n.id === e.source)!)
    .filter(Boolean);
  const owner = (
    <Field label={node.type === 'human_review' ? 'Reviewer' : 'Human owner'}>
      <select value={c.owner_id || ''} onChange={(e) => set({ owner_id: e.target.value })}>
        <option value="">Choose a member</option>
        {wf.project.members.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
    </Field>
  );
  const ownerConnection = wf.project.members.find((member) => member.id === c.owner_id)?.connection;
  return (
    <aside className="inspector">
      <div className="panel-head">
        <span>
          <SlidersHorizontal size={16} />
          Block settings
        </span>
        <button className="icon-button" title="Close settings" onClick={onClose}>
          <X size={17} />
        </button>
      </div>
      <div className="inspector-scroll">
        <div className="inspector-type" style={{ color: KINDS[node.type].color }}>
          <Icon size={20} />
          {KINDS[node.type].name}
        </div>
        <Field label="Block name">
          <input
            value={node.label}
            onChange={(e) => onChange({ ...node, label: e.target.value })}
          />
        </Field>
        {node.type === 'agent_task' && (
          <>
            <div className="section-label">
              <UserRound size={14} />
              Assignment
            </div>
            <Field label="Agent">
              <select value={c.agent_id || ''} onChange={(e) => set({ agent_id: e.target.value })}>
                <option value="">Choose an agent</option>
                {wf.agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
            <button className="text-button" onClick={onAgents}>
              Manage agents ↗
            </button>
            {owner}
            <div className="owner-connection-summary" aria-label="Owner model connection">
              <strong>When running with OpenCode</strong>
              <span>{ownerConnection?.model || 'The owner has no model configured.'}</span>
              {ownerConnection && (
                <small>
                  {credentials[ownerConnection.credential_ref] === true
                    ? 'API key saved on this device'
                    : credentials[ownerConnection.credential_ref] === false
                      ? 'API key not configured on this device'
                      : 'API key status not checked on this device'}
                </small>
              )}
              <button className="text-button" onClick={onMembers}>
                Manage member connections ↗
              </button>
            </div>
            <Field label="Task instructions">
              <textarea
                rows={5}
                placeholder="What should this agent do?"
                value={c.instructions || ''}
                onChange={(e) => set({ instructions: e.target.value })}
              />
            </Field>
            <Field label="Acceptance criteria">
              <textarea
                rows={3}
                placeholder="What does a good result look like?"
                value={c.acceptance || ''}
                onChange={(e) => set({ acceptance: e.target.value })}
              />
            </Field>
            <Field label="Output format">
              <select
                value={c.output_format || 'markdown'}
                onChange={(e) => set({ output_format: e.target.value as Config['output_format'] })}
              >
                <option value="markdown">Markdown</option>
                <option value="json">JSON</option>
                <option value="csv">CSV</option>
              </select>
            </Field>
            <div className="section-label">
              <ShieldCheck size={14} />
              Tools & permissions
            </div>
            <CheckList
              values={TOOLS}
              selected={c.tools || []}
              onChange={(tools) => set({ tools })}
            />
            <Field label="Readable paths">
              <textarea
                rows={2}
                placeholder="inputs/brief.txt"
                value={c.permissions?.read.join('\n') || ''}
                onChange={(e) =>
                  set({
                    permissions: {
                      read: e.target.value.split('\n').filter(Boolean),
                      write: c.permissions?.write || [],
                    },
                  })
                }
              />
            </Field>
            <Field label="Writable paths">
              <textarea
                rows={2}
                placeholder="results/drafts/"
                value={c.permissions?.write.join('\n') || ''}
                onChange={(e) =>
                  set({
                    permissions: {
                      read: c.permissions?.read || [],
                      write: e.target.value.split('\n').filter(Boolean),
                    },
                  })
                }
              />
            </Field>
          </>
        )}
        {node.type === 'shared_resource' && (
          <>
            <Field label="Available resources">
              <div className="check-list">
                {wf.resources.length ? (
                  wf.resources.map((r) => (
                    <label key={r.id}>
                      <input
                        type="checkbox"
                        checked={c.resource_ids?.includes(r.id) || false}
                        onChange={(e) =>
                          set({
                            resource_ids: e.target.checked
                              ? [...(c.resource_ids || []), r.id]
                              : (c.resource_ids || []).filter((id) => id !== r.id),
                          })
                        }
                      />
                      <span>{r.name}</span>
                    </label>
                  ))
                ) : (
                  <p className="muted">No resources yet.</p>
                )}
              </div>
            </Field>
          </>
        )}
        {node.type === 'human_review' && (
          <>
            {owner}
            <Field label="Review instructions">
              <textarea
                rows={5}
                value={c.instructions || ''}
                onChange={(e) => set({ instructions: e.target.value })}
              />
            </Field>
          </>
        )}
        {node.type === 'condition' && (
          <>
            <Field label="Result to inspect">
              <select
                value={c.source_node || ''}
                onChange={(e) => set({ source_node: e.target.value })}
              >
                <option value="">Choose a connected data source</option>
                {dataSources.map((n) => (
                  <option value={n.id} key={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="JSON field path">
              <input
                value={c.field || ''}
                placeholder="data.approved"
                onChange={(e) => set({ field: e.target.value })}
              />
            </Field>
            <Field label="Comparison">
              <select
                value={c.operator || 'eq'}
                onChange={(e) => set({ operator: e.target.value as Config['operator'] })}
              >
                <option value="eq">Equals</option>
                <option value="neq">Does not equal</option>
                <option value="gt">Greater than</option>
                <option value="contains">Contains</option>
              </select>
            </Field>
            <Field label="Value">
              <input
                defaultValue={JSON.stringify(c.value)}
                key={node.id + '-value-' + JSON.stringify(c.value)}
                onBlur={(e) => {
                  try {
                    set({ value: JSON.parse(e.target.value) });
                  } catch {
                    set({ value: e.target.value });
                  }
                }}
              />
            </Field>
          </>
        )}
        {node.type === 'output' && (
          <>
            {(c.mappings || []).map((m, i) => (
              <div className="mapping-card" key={i}>
                <Field label="Source result">
                  <select
                    value={m.source_node}
                    onChange={(e) =>
                      set({
                        mappings: c.mappings!.map((x, j) =>
                          i === j ? { ...x, source_node: e.target.value } : x,
                        ),
                      })
                    }
                  >
                    <option value="">Choose data source</option>
                    {dataSources.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Filename">
                  <input
                    value={m.filename}
                    onChange={(e) =>
                      set({
                        mappings: c.mappings!.map((x, j) =>
                          i === j ? { ...x, filename: e.target.value } : x,
                        ),
                      })
                    }
                  />
                </Field>
                <div className="row">
                  <select
                    value={m.format}
                    onChange={(e) =>
                      set({
                        mappings: c.mappings!.map((x, j) =>
                          i === j ? { ...x, format: e.target.value as Mapping['format'] } : x,
                        ),
                      })
                    }
                  >
                    <option value="markdown">Markdown</option>
                    <option value="json">JSON</option>
                    <option value="csv">CSV</option>
                  </select>
                  <button
                    className="icon-button danger"
                    title="Remove file mapping"
                    onClick={() => set({ mappings: c.mappings!.filter((_, j) => j !== i) })}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
            <button
              className="secondary full"
              onClick={() =>
                set({
                  mappings: [
                    ...(c.mappings || []),
                    {
                      source_node: dataSources[0]?.id || '',
                      filename: 'report.md',
                      format: 'markdown',
                    },
                  ],
                })
              }
            >
              <Plus size={15} />
              Add delivery file
            </button>
          </>
        )}
        {node.type !== 'start' && (
          <>
            <div className="section-label">
              <ArrowDown size={14} />
              Dependencies
            </div>
            <Field label="Join rule">
              <select
                value={c.join_rule || 'all_selected'}
                onChange={(e) => set({ join_rule: e.target.value as Config['join_rule'] })}
              >
                <option value="all_selected">Wait for all selected branches</option>
                <option value="all_success">Require every branch to succeed</option>
              </select>
            </Field>
            <Field label="Shared input results">
              <div className="dependency-list">
                {dataSources.length ? (
                  dataSources.map((n) => <span key={n.id}>{n.label}</span>)
                ) : (
                  <p>No connected results</p>
                )}
              </div>
            </Field>
          </>
        )}
      </div>
      <div className="inspector-actions">
        <button className="secondary" onClick={onDuplicate}>
          <Copy size={15} />
          Duplicate
        </button>
        <button className="icon-button danger" title="Delete block" onClick={onDelete}>
          <Trash2 size={17} />
        </button>
      </div>
    </aside>
  );
}
