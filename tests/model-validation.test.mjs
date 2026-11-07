import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { assertSafeWorkflow, emptyWorkflow, parseWorkflow } from '../src/model.ts';

const template = JSON.parse(readFileSync(new URL('../examples/team-research.json', import.meta.url), 'utf8'));
const changed = fn => { const workflow = structuredClone(template); fn(workflow); return workflow; };

test('complete demo and incomplete editable workspace preserve all fields', () => {
  assert.deepEqual(parseWorkflow(template), template);
  const empty = emptyWorkflow();
  assert.deepEqual(parseWorkflow(empty), empty);
});

test('rejects malformed nested arrays without leaving a broken workspace', () => {
  for (const change of [
    w => { w.agents[0].tools = [{}]; },
    w => { w.project.members = [null]; },
    w => { w.nodes[0].config.join_rule = ['all_selected']; },
    w => { w.nodes[0].position.x = '42'; },
    w => { w.nodes[0].config.permissions = { read: {}, write: [] }; },
  ]) assert.throws(() => parseWorkflow(changed(change)));
});

test('rejects duplicate IDs and invalid ports', () => {
  assert.throws(() => parseWorkflow(changed(w => w.nodes.push(structuredClone(w.nodes[0])))), /Duplicate/);
  assert.throws(() => parseWorkflow(changed(w => { w.edges[0].source_port = 'data-out'; })), /ports/);
});

test('rejects cycles introduced through either dependency kind', () => {
  assert.throws(() => parseWorkflow(changed(w => w.edges.push({
    id: 'cycle', source: 'synthesis', target: 'research', kind: 'data', source_port: 'data-out', target_port: 'data-in',
  }))), /cycle/);
});

test('blocks explicit secret fields and key patterns before local persistence', () => {
  assert.throws(() => assertSafeWorkflow(changed(w => { w.nodes[0].config.api_key = 'not-a-real-key'; })), /Secret/);
  assert.throws(() => assertSafeWorkflow(changed(w => { w.agents[0].system_prompt = 'sk-proj-TESTONLY00000000000000000000'; })), /API key/);
  assert.throws(() => assertSafeWorkflow(changed(w => { w.nodes[0].config['sk-proj-TESTONLY00000000000000000000'] = 'hidden in a dictionary key'; })), /API key/);
  assert.throws(() => assertSafeWorkflow(changed(w => { w.agents[0].credential_ref = 'not an env reference'; })), /Credential/);
  assert.doesNotThrow(() => assertSafeWorkflow(template));
});
