import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { presetConnection, connectionPreset } from '../src/connections.ts';
import { parseWorkflow, assertSafeWorkflow } from '../src/model.ts';
import {
  memberCredentialRef,
  newMemberConnection,
  ownerConnectionIssues,
} from '../src/owner-connections.ts';

test('DeepSeek preset survives workflow serialization using the existing OpenAI adapter', () => {
  const workflow = JSON.parse(
    readFileSync(new URL('../examples/team-research.json', import.meta.url), 'utf8'),
  );
  const connection = presetConnection('deepseek');
  workflow.agents[0] = { ...workflow.agents[0], ...connection };
  const restored = parseWorkflow(JSON.parse(JSON.stringify(workflow)));
  assert.equal(restored.agents[0].provider, 'openai');
  assert.equal(restored.agents[0].credential_ref, 'DEEPSEEK_API_KEY');
  assert.equal(restored.agents[0].base_url, 'https://api.deepseek.com');
  assert.equal(connectionPreset(restored.agents[0]), 'deepseek');
  assertSafeWorkflow(restored);
});

test('provider changes clear incompatible model and endpoint without carrying a secret field', () => {
  for (const preset of ['openai', 'anthropic', 'custom']) {
    const connection = presetConnection(preset);
    assert.equal(connection.model, '');
    assert.equal(connection.base_url, '');
    assert.equal(connectionPreset(connection), preset);
    assert.deepEqual(Object.keys(connection).sort(), [
      'base_url',
      'credential_ref',
      'model',
      'provider',
    ]);
  }
});

test('member connections keep independent credential references across provider changes and renames', () => {
  const first = newMemberConnection('project-1', 'member-1');
  const second = newMemberConnection('project-1', 'member-2');
  assert.notEqual(first.credential_ref, second.credential_ref);
  assert.notEqual(first.credential_ref, memberCredentialRef('project-2', 'member-1'));
  assert.notEqual(memberCredentialRef('a-b', 'c'), memberCredentialRef('a_b', 'c'));
  assert.notEqual(memberCredentialRef('Project', 'c'), memberCredentialRef('project', 'c'));
  assert.match(first.credential_ref, /^[A-Z][A-Z0-9_]{0,99}$/);
  for (const preset of ['openai', 'anthropic', 'deepseek', 'custom']) {
    const next = presetConnection(preset, first.credential_ref);
    assert.equal(next.credential_ref, first.credential_ref);
    assert.equal(connectionPreset(next), preset);
  }
  const member = { id: 'member-1', name: 'Old name', skills: '', connection: first };
  member.name = 'New name';
  assert.equal(member.connection.credential_ref, memberCredentialRef('project-1', member.id));
});

function configuredOwnerWorkflow() {
  const workflow = JSON.parse(
    readFileSync(new URL('../examples/team-research.json', import.meta.url), 'utf8'),
  );
  for (const member of workflow.project.members) {
    member.connection = {
      ...newMemberConnection(workflow.project.id, member.id),
      model: `fixture-${member.id}-model`,
    };
  }
  return workflow;
}

test('OpenCode follows task owners even when different owners share one agent role', () => {
  const workflow = configuredOwnerWorkflow();
  const tasks = workflow.nodes.filter((node) => node.type === 'agent_task');
  tasks[1].config.agent_id = tasks[0].config.agent_id;
  assert.deepEqual(ownerConnectionIssues(workflow), []);
  const owner = workflow.project.members.find((member) => member.id === tasks[1].config.owner_id);
  owner.connection.model = '';
  const issues = ownerConnectionIssues(workflow);
  assert.ok(
    issues.some((issue) => issue.node_id === tasks[1].id && issue.message.includes(owner.name)),
  );
  assert.ok(!issues.some((issue) => issue.node_id === tasks[0].id));
  tasks[1].config.owner_id = tasks[0].config.owner_id;
  assert.deepEqual(ownerConnectionIssues(workflow), []);
});

test('OpenCode export rejects missing owners, shared keys and unsafe endpoints before running', () => {
  const workflow = configuredOwnerWorkflow();
  const tasks = workflow.nodes.filter((node) => node.type === 'agent_task');
  const ownerA = workflow.project.members.find((member) => member.id === tasks[0].config.owner_id);
  const ownerB = workflow.project.members.find((member) => member.id === tasks[1].config.owner_id);
  ownerB.connection.credential_ref = ownerA.connection.credential_ref;
  assert.ok(
    ownerConnectionIssues(workflow).some((issue) =>
      issue.message.includes('share a credential reference'),
    ),
  );
  ownerB.connection = newMemberConnection(workflow.project.id, ownerB.id);
  ownerB.connection.model = 'fixture-model';
  const credentialUrl = new URL('https://example.invalid/v1');
  credentialUrl.username = 'fixture-user';
  credentialUrl.password = 'fixture-password';
  ownerB.connection.base_url = credentialUrl.href;
  assert.ok(
    ownerConnectionIssues(workflow).some((issue) => issue.message.includes('without credentials')),
  );
  ownerB.connection.base_url = 'http://127.0.0.1:9999/v1';
  assert.deepEqual(ownerConnectionIssues(workflow), []);
  tasks[1].config.owner_id = 'deleted-member';
  assert.ok(ownerConnectionIssues(workflow).some((issue) => issue.node_id === tasks[1].id));
});

test('a review-only member does not need an API connection', () => {
  const workflow = configuredOwnerWorkflow();
  workflow.project.members.push({ id: 'review-only', name: 'Reviewer', skills: '' });
  workflow.nodes.find((node) => node.type === 'human_review').config.owner_id = 'review-only';
  assert.deepEqual(ownerConnectionIssues(workflow), []);
});
