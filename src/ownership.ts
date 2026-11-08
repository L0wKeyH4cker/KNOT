import { assertSafeWorkflow, uid } from './model.ts';
import type { Member, Workflow } from './model.ts';

export const ownerKey = (name: string) => name.trim().toLocaleLowerCase();

export function ownerName(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw Error('Enter a person’s name.');
  if (value.trim().length > 300) throw Error('Use a name of 300 characters or fewer.');
  return value.trim();
}

export function isDefaultOwner(member: Member): boolean {
  return (
    !member.skills.trim() &&
    ((member.id === 'project-owner' && member.name === 'Project owner') ||
      (/^member[_-]\d+$/.test(member.id) && /^Member (?:[A-Z]|\d+)$/.test(member.name)))
  );
}

/** Assign a name to one task without renaming the owners of other tasks. */
export function assignOwner(wf: Workflow, nodeId: string, value: string): Workflow {
  const name = ownerName(value);
  const node = wf.nodes.find((item) => item.id === nodeId);
  if (!node || !['agent_task', 'human_review'].includes(node.type))
    throw Error('Choose a task or review before assigning an owner.');
  const existing = wf.project.members.find((member) => ownerKey(member.name) === ownerKey(name));
  const member = existing || { id: uid('member'), name, skills: '' };
  // There is no standalone roster editor. Reclaim unused name-only entries at
  // the limit so repeatedly reassigning a task cannot permanently fill it up.
  let members = wf.project.members;
  if (!existing && members.length >= 50) {
    const referenced = new Set(
      wf.nodes.filter((item) => item.id !== nodeId).map((item) => item.config.owner_id),
    );
    members = members.filter((item) => referenced.has(item.id) || item.skills.trim());
    if (members.length >= 50)
      throw Error('This project already has 50 people. Choose an existing name.');
  }
  const next = {
    ...wf,
    project: {
      ...wf.project,
      members: existing ? members : [...members, member],
    },
    nodes: wf.nodes.map((item) =>
      item.id === nodeId ? { ...item, config: { ...item.config, owner_id: member.id } } : item,
    ),
  };
  assertSafeWorkflow(next);
  return next;
}

/** Named requirements replace generated placeholders; real existing people keep their IDs. */
export function ownersFromRequirements(members: Member[], names: string[]): Member[] {
  if (!names.length) return members;
  const next = members.filter((member) => !isDefaultOwner(member));
  for (const value of names) {
    const name = ownerName(value);
    if (!next.some((member) => ownerKey(member.name) === ownerKey(name))) {
      next.push(
        members.find((member) => ownerKey(member.name) === ownerKey(name)) || {
          id: uid('member'),
          name,
          skills: '',
        },
      );
    }
  }
  if (next.length > 50) throw Error('A project can have at most 50 people.');
  return next;
}
