import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { presetConnection, connectionPreset } from '../src/connections.ts';
import { parseWorkflow, assertSafeWorkflow } from '../src/model.ts';

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
