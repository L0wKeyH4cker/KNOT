import { Handle, Position } from '@xyflow/react';
import {
  Play,
  Bot,
  FolderOpen,
  GitFork,
  GitBranch,
  UserCheck,
  Package,
  MoreHorizontal,
} from 'lucide-react';
import type { CSSProperties } from 'react';
import { KINDS } from './model';
import type { Block, Workflow, NodeKind } from './model';
export const icons = {
  start: Play,
  agent_task: Bot,
  shared_resource: FolderOpen,
  parallel: GitFork,
  condition: GitBranch,
  human_review: UserCheck,
  output: Package,
};
export default function BlockNode({
  data,
  selected,
}: {
  data: { block: Block; workflow: Workflow };
  selected?: boolean;
}) {
  const { block: n, workflow: w } = data,
    meta = KINDS[n.type],
    Icon = icons[n.type as NodeKind];
  const agent = w.agents.find((a) => a.id === n.config.agent_id),
    owner = w.project.members.find((m) => m.id === n.config.owner_id);
  const detail =
    n.type === 'agent_task'
      ? n.config.instructions || 'Add task instructions'
      : n.type === 'shared_resource'
        ? `${n.config.resource_ids?.length || 0} input resources`
        : n.type === 'parallel'
          ? 'Independent tasks run together'
          : n.type === 'condition'
            ? `${n.config.field} ${n.config.operator} ${JSON.stringify(n.config.value)}`
            : n.type === 'human_review'
              ? 'Pauses until a person approves'
              : n.type === 'output'
                ? `${n.config.mappings?.length || 0} delivery files`
                : 'Your team’s starting point';
  return (
    <div
      className={`block-card ${selected ? 'is-selected' : ''} ${n.type}`}
      style={{ '--block-color': meta.color } as CSSProperties}
      data-testid={`block-${n.id}`}
    >
      {n.type !== 'start' && (
        <Handle
          type="target"
          id="in"
          position={Position.Left}
          className="control-handle"
          title="Execution input"
        />
      )}
      <div className="block-eyebrow">
        <span className="block-symbol">
          <Icon size={15} />
        </span>
        {meta.name}
        <MoreHorizontal size={16} className="block-more" />
      </div>
      <h3>{n.label}</h3>
      <p>{detail}</p>
      {n.type === 'agent_task' && (
        <div className="block-footer">
          <span>
            <Bot size={12} />
            {agent?.name || 'Select agent'}
          </span>
          <span className="mini-avatar" title={owner?.name || 'No owner'}>
            {owner?.name.slice(0, 1) || '?'}
          </span>
        </div>
      )}
      {n.type === 'human_review' && (
        <div className="block-footer">
          <span>
            <UserCheck size={12} />
            {owner?.name || 'Choose reviewer'}
          </span>
          <span className="small-pill">Approval</span>
        </div>
      )}
      {n.type === 'output' && n.config.mappings?.length ? (
        <div className="file-chips">
          {n.config.mappings.map((m) => (
            <span key={m.filename}>{m.filename}</span>
          ))}
        </div>
      ) : null}
      {n.type !== 'output' && n.type !== 'condition' && (
        <Handle
          type="source"
          id="out"
          position={Position.Right}
          className="control-handle"
          title="Execution output"
        />
      )}
      {n.type === 'condition' && (
        <>
          <Handle
            type="source"
            id="true"
            position={Position.Right}
            style={{ top: '35%' }}
            className="control-handle true-port"
            title="True branch"
          />
          <span className="port-label true-label">T</span>
          <Handle
            type="source"
            id="false"
            position={Position.Right}
            style={{ top: '75%' }}
            className="control-handle false-port"
            title="False branch"
          />
          <span className="port-label false-label">F</span>
        </>
      )}
      {n.type !== 'start' && (
        <Handle
          type="target"
          id="data-in"
          position={Position.Top}
          className="data-handle"
          title="Data input: grants access to upstream result"
        />
      )}
      <Handle
        type="source"
        id="data-out"
        position={Position.Bottom}
        className="data-handle"
        title="Data output: share result"
      />
    </div>
  );
}
