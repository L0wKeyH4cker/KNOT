import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from '../src/model.ts';

test('API validation failures identify each node and deduplicate only identical issues', async (t) => {
  const message = 'Connect this node to Start with execution connections';
  const first = { code: 'unreachable', node_id: 'requirements-source', message };
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    error: 'Workflow validation failed.',
    issues: [first, { ...first }, { ...first, node_id: 'requirements-analysis' }],
    debug: 'private backend detail',
  }), { status: 422 }));

  await assert.rejects(api('plan', { project: {} }), {
    message: `Workflow validation failed.\n- [requirements-source] ${message}\n- [requirements-analysis] ${message}`,
  });
});

test('API errors preserve legacy message-only issues and ignore unsupported detail fields', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    message: 'Could not generate a workflow.',
    issues: [{ message: 'Choose an owner.', raw_response: 'private provider text' }],
  }), { status: 422 }));

  await assert.rejects(api('plan'), {
    message: 'Could not generate a workflow.\n- Choose an owner.',
  });
});

test('malformed API error fields do not hide valid messages or stringify unexpected objects', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    error: { secret: 'private value' },
    message: 'Validation failed.',
    issues: [null, {}, 'invalid', { message: { secret: 'private issue value' } },
      { message: 'Connect the node.', node_id: { secret: 'private ID' } }],
  }), { status: 422 }));

  await assert.rejects(api('plan'), {
    message: 'Validation failed.\n- Connect the node.',
  });
});

test('non-JSON API failures retain the HTTP status fallback', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('Unavailable', { status: 503 }));
  await assert.rejects(api('plan'), { message: 'Server error (503)' });
});
