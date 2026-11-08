import { presetConnection } from './connections.ts';
import type { ModelConnection } from './connections.ts';
import type { Issue, Workflow } from './model.ts';

// Stable identifiers only: this hash never contains or processes a secret.
// Keep references short enough for the shared 100-character environment-name limit.
function idHash(value: string): string {
  let hash = 0xcbf29ce484222325n;
  for (const byte of new TextEncoder().encode(value)) {
    hash = BigInt.asUintN(64, (hash ^ BigInt(byte)) * 0x100000001b3n);
  }
  return hash.toString(16).padStart(16, '0').toUpperCase();
}

export function memberCredentialRef(projectId: string, memberId: string): string {
  return `KNOT_P${idHash(projectId)}_M${idHash(memberId)}_KEY`;
}

export function newMemberConnection(projectId: string, memberId: string): ModelConnection {
  return {
    ...presetConnection('openai'),
    base_url: 'https://api.openai.com/v1',
    credential_ref: memberCredentialRef(projectId, memberId),
  };
}

export function ownerConnectionIssues(workflow: Workflow): Issue[] {
  const issues: Issue[] = [];
  const members = new Map(workflow.project.members.map((member) => [member.id, member]));
  const usedRefs = new Map<string, string>();
  const usedOwners = new Set<string>();
  for (const node of workflow.nodes) {
    if (node.type !== 'agent_task') continue;
    const member = members.get(node.config.owner_id || '');
    const add = (message: string) =>
      issues.push({ severity: 'error', code: 'owner_connection', node_id: node.id, message });
    if (!member) {
      add(`${node.label}: choose an existing team member for OpenCode execution.`);
      continue;
    }
    const connection = member.connection;
    if (!connection) {
      add(
        `${node.label}: configure ${member.name}'s connection in Project settings → Team members.`,
      );
      continue;
    }
    const model = connection.model.trim();
    if (!model) add(`${node.label}: enter a model for ${member.name}.`);
    else if (
      !/^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,199}$/.test(model) ||
      /^[A-Za-z]:/.test(model) ||
      model.split('/').some((part) => part === '.' || part === '..')
    )
      add(`${node.label}: ${member.name}'s model must be a model ID, not a command or file path.`);
    if (!/^[A-Z][A-Z0-9_]{0,99}$/.test(connection.credential_ref))
      add(`${node.label}: ${member.name} needs a valid credential reference.`);
    if (connection.base_url) {
      try {
        const base = connection.base_url.trim();
        if (base.length > 2048 || /[\u0000-\u0020]/.test(base)) throw new Error('Invalid endpoint');
        const url = new URL(base);
        if (
          url.username ||
          url.password ||
          url.search ||
          url.hash ||
          !(
            url.protocol === 'https:' ||
            (url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
          )
        )
          throw new Error('Invalid endpoint');
      } catch {
        add(
          `${node.label}: ${member.name}'s API address must use HTTPS or local HTTP without credentials.`,
        );
      }
    }
    if (!usedOwners.has(member.id)) {
      const previous = usedRefs.get(connection.credential_ref);
      if (previous !== undefined)
        add(
          `${member.name} and ${previous} share a credential reference. Configure a separate connection for each member.`,
        );
      usedOwners.add(member.id);
      usedRefs.set(connection.credential_ref, member.name);
    }
  }
  return issues;
}
