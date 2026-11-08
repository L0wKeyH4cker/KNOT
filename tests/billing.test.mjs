import assert from 'node:assert/strict';
import test from 'node:test';
import {
  emptyBillingLedger,
  parseUsageReport,
  mergeUsageReport,
  parseBillingLedger,
  confirmEntry,
  clearConfirmation,
  addSharedExpense,
  removeSharedExpense,
  summarizeBilling,
  ledgerEntriesCsv,
  settlementCsv,
  exportBillingLedger,
} from '../src/billing.ts';

const start = '2026-11-07T12:00:00.000Z';
const updated = '2026-11-07T12:01:00.000Z';
const later = '2026-11-07T12:02:00.000Z';
const confirmedAt = '2026-11-07T12:03:00.000Z';

function entry(overrides = {}) {
  return {
    id: 'run-1:task-1:1',
    run_id: 'run-1',
    node_id: 'task-1',
    node_label: 'Outreach',
    agent_id: 'agent-1',
    agent_name: 'Outreach agent',
    owner_id: 'sam',
    owner_name: 'Sam Rivera',
    provider: 'codex',
    model: '',
    attempt: 1,
    status: 'succeeded',
    usage_status: 'reported',
    usage: {
      input_tokens: 100,
      output_tokens: 20,
      cached_input_tokens: 30,
      cache_creation_input_tokens: 0,
    },
    started_at: start,
    updated_at: updated,
    ...overrides,
  };
}
function report(entries = [entry()], overrides = {}) {
  return {
    kind: 'knot-usage',
    schema_version: '1.0',
    project: { id: 'project', name: 'Repair fair' },
    run_id: 'run-1',
    updated_at: updated,
    entries,
    ...overrides,
  };
}
function ledger(entries = [entry()]) {
  return mergeUsageReport(emptyBillingLedger('project'), report(entries));
}
function confirmed(value, id, amount = '1.25', currency = 'USD', extra = {}) {
  return confirmEntry(
    value,
    id,
    { amount, currency, source: 'Invoice 2026-001', ...extra },
    confirmedAt,
  );
}
const participants = [
  { id: 'c', name: 'C' },
  { id: 'b', name: 'B' },
  { id: 'a', name: 'A' },
];

test('usage reports keep ownership snapshots and unknown amounts distinct from explicit zero', () => {
  const original = report();
  const imported = ledger();
  assert.equal(imported.entries[0].owner_name, 'Sam Rivera');
  original.entries[0].owner_name = 'Changed on the canvas';
  assert.equal(imported.entries[0].owner_name, 'Sam Rivera');
  assert.equal(summarizeBilling(imported).unknown_count, 1);
  assert.equal(summarizeBilling(imported).currencies.length, 0);
  const zero = confirmed(imported, imported.entries[0].id, '0');
  assert.equal(summarizeBilling(zero).unknown_count, 0);
  assert.deepEqual(summarizeBilling(zero).currencies, [
    { currency: 'USD', confirmed: '0', estimated: '0', settlement: '0.00' },
  ]);
  assert.equal(summarizeBilling(zero).members[0].total, '0.00');
});

test('importing the same report twice never duplicates calls or removes confirmed fees', () => {
  const first = confirmed(ledger(), entry().id);
  const next = mergeUsageReport(first, report());
  assert.equal(next.revision, first.revision);
  assert.equal(next.entries.length, 1);
  assert.deepEqual(next.confirmed, first.confirmed);
  assert.equal(summarizeBilling(next).members[0].total, '1.25');
});

test('separate attempts and separate runs remain separate costs, including failed attempts', () => {
  const first = entry({ status: 'failed' });
  const retry = entry({ id: 'run-1:task-1:2', attempt: 2, started_at: updated, updated_at: later });
  let value = ledger([first, retry]);
  value = confirmed(value, first.id, '0.25');
  value = confirmed(value, retry.id, '1');
  const other = entry({ id: 'run-2:task-1:1', run_id: 'run-2' });
  value = mergeUsageReport(value, report([other], { run_id: 'run-2' }));
  value = confirmed(value, other.id, '2');
  assert.equal(value.entries.length, 3);
  const summary = summarizeBilling(value);
  assert.equal(summary.agents[0].entry_count, 3);
  assert.equal(summary.agents[0].input_tokens, 300);
  assert.equal(summary.members[0].total, '3.25');
});

test('older snapshots cannot roll reported usage back or change the execution identity', () => {
  const current = ledger([entry({ updated_at: later })]);
  const old = report([
    entry({
      usage_status: 'unknown',
      usage: {
        input_tokens: null,
        output_tokens: null,
        cached_input_tokens: null,
        cache_creation_input_tokens: null,
      },
    }),
  ]);
  assert.deepEqual(mergeUsageReport(current, old), current);
  for (const patch of [
    { owner_id: 'maya' },
    { agent_id: 'another-agent' },
    { node_id: 'other-task' },
    { attempt: 2 },
    { owner_name: 'Maya' },
  ]) {
    assert.throws(
      () => mergeUsageReport(current, report([entry({ ...patch, updated_at: later })])),
      /responsibility/,
    );
  }
});

test('new usage or model information marks a prior confirmation for review without discarding it', () => {
  const original = confirmed(ledger(), entry().id, '0.35');
  const next = mergeUsageReport(
    original,
    report([
      entry({
        model: 'reported-model',
        updated_at: later,
        usage: { ...entry().usage, input_tokens: 300 },
      }),
    ]),
  );
  assert.equal(next.entries[0].model, 'reported-model');
  assert.equal(next.confirmed[0].amount, '0.35');
  assert.equal(next.confirmed[0].source, 'Invoice 2026-001');
  assert.equal(next.confirmed[0].needs_review, true);
  assert.equal(summarizeBilling(next).review_count, 1);
  assert.equal(summarizeBilling(next).members.length, 0);
  const renewed = confirmed(next, entry().id, '0.45');
  assert.equal(summarizeBilling(renewed).members[0].total, '0.45');
  assert.equal(summarizeBilling(renewed).review_count, 0);
  assert.equal(original.confirmed[0].needs_review, false);
});

test('an updated timestamp alone does not invalidate a checked invoice', () => {
  const value = confirmed(ledger(), entry().id);
  const next = mergeUsageReport(value, report([entry({ updated_at: later })]));
  assert.equal(next.confirmed[0].needs_review, false);
});

test('runtime microsecond timestamps order rapid snapshots without dropping final usage', () => {
  const original = ledger([
    entry({ status: 'running', updated_at: '2026-11-07T12:01:00.123100Z' }),
  ]);
  const next = mergeUsageReport(
    original,
    report([entry({ updated_at: '2026-11-07T12:01:00.123900Z' })]),
  );
  assert.equal(next.entries[0].status, 'succeeded');
  assert.throws(
    () =>
      mergeUsageReport(
        next,
        report([entry({ status: 'failed', updated_at: '2026-11-07T12:01:00.123900Z' })]),
      ),
    /same update time/,
  );
  assert.throws(
    () => parseUsageReport(report([entry({ started_at: '2026-02-30T00:00:00Z' })]), 'project'),
    /calendar/,
  );
});

test('ledger backups cannot silently settle a still-running execution', () => {
  const saved = confirmed(ledger(), entry().id);
  saved.entries[0].status = 'running';
  assert.throws(() => parseBillingLedger(saved, 'project'), /running/);
  saved.confirmed[0].needs_review = true;
  assert.equal(parseBillingLedger(saved, 'project').confirmed[0].needs_review, true);
  assert.equal(summarizeBilling(saved).members.length, 0);
});

test('CLI estimates never enter settlement, and confirmation replaces rather than adds to estimates', () => {
  const estimated = entry({
    estimated_cost: { amount: '0.250001', currency: 'USD', source: 'CLI estimate' },
  });
  const value = ledger([estimated]);
  assert.equal(summarizeBilling(value).members.length, 0);
  assert.deepEqual(summarizeBilling(value).currencies, [
    { currency: 'USD', confirmed: '0', estimated: '0.250001', settlement: '0.00' },
  ]);
  const actual = confirmed(value, estimated.id, '0.3');
  assert.equal(summarizeBilling(actual).currencies[0].estimated, '0');
  assert.equal(summarizeBilling(actual).currencies[0].confirmed, '0.3');
  assert.equal(actual.entries[0].estimated_cost.amount, '0.250001');
});

test('one shared Agent charge is counted once and split across the selected members', () => {
  const value = confirmed(ledger(), entry().id, '0.01', 'USD', {
    allocation: 'shared',
    participants,
  });
  const summary = summarizeBilling(value);
  assert.equal(summary.agents[0].confirmed.USD, '0.01');
  assert.equal(summary.currencies[0].confirmed, '0.01');
  assert.deepEqual(
    summary.members.map((person) => [person.id, person.total]),
    [
      ['a', '0.01'],
      ['b', '0.00'],
      ['c', '0.00'],
    ],
  );
  assert.equal(
    summary.members.some((person) => person.id === 'sam'),
    false,
  );
});

test('standalone shared expenses use fixed participant snapshots and sum to the charged cent', () => {
  const people = structuredClone(participants);
  const value = addSharedExpense(
    emptyBillingLedger('project'),
    {
      id: 'shared-1',
      description: 'Shared planning',
      amount: '0.01',
      currency: 'USD',
      source: 'Invoice P',
      participants: people,
    },
    confirmedAt,
  );
  people[0].name = 'Later renamed';
  const summary = summarizeBilling(value);
  assert.deepEqual(
    summary.members.map((person) => person.name),
    ['A', 'B', 'C'],
  );
  assert.deepEqual(
    summary.members.map((person) => person.total),
    ['0.01', '0.00', '0.00'],
  );
  assert.equal(summary.currencies[0].settlement, '0.01');
  assert.equal(removeSharedExpense(value, 'shared-1').shared.length, 0);
  assert.equal(value.shared.length, 1);
});

test('micro amounts accumulate before rounding, and same-Agent different-member costs stay distinct', () => {
  const second = entry({
    id: 'run-1:task-2:1',
    node_id: 'task-2',
    owner_id: 'maya',
    owner_name: 'Maya Chen',
  });
  let value = ledger([entry(), second]);
  value = confirmed(value, entry().id, '0.004');
  value = confirmed(value, second.id, '0.004');
  const summary = summarizeBilling(value);
  assert.equal(summary.agents.length, 2);
  assert.equal(summary.currencies[0].confirmed, '0.008');
  assert.equal(summary.currencies[0].settlement, '0.01');
  assert.deepEqual(
    summary.members.map((person) => [person.id, person.total]),
    [
      ['maya', '0.01'],
      ['sam', '0.00'],
    ],
  );
});

test('currencies remain separate without an invented exchange rate', () => {
  const second = entry({ id: 'run-1:task-2:1', node_id: 'task-2' });
  let value = ledger([entry(), second]);
  value = confirmed(value, entry().id, '2', 'USD');
  value = confirmed(value, second.id, '3', 'CNY');
  assert.deepEqual(
    summarizeBilling(value).members.map((person) => [person.currency, person.total]),
    [
      ['CNY', '3.00'],
      ['USD', '2.00'],
    ],
  );
  assert.equal(summarizeBilling(value).currencies.length, 2);
});

test('unknown and partial usage stays unknown or explicitly partial, with cache not added twice', () => {
  const full = summarizeBilling(ledger());
  assert.equal(full.agents[0].input_tokens, 100); // Includes the 30 cached tokens.
  const partial = entry({
    usage_status: 'partial',
    usage: {
      input_tokens: 10,
      output_tokens: null,
      cached_input_tokens: 20,
      cache_creation_input_tokens: null,
    },
  });
  const summary = summarizeBilling(ledger([partial]));
  assert.equal(summary.partial_count, 1);
  assert.equal(summary.agents[0].input_tokens, 10);
  assert.equal(summary.agents[0].output_tokens, null);
  assert.throws(
    () => parseUsageReport(report([{ ...partial, usage_status: 'reported' }]), 'project'),
    /Cached/,
  );
});

test('mock runs cannot be confirmed and running attempts must stop before a fee is confirmed', () => {
  const simulated = entry({
    usage_status: 'simulated',
    usage: {
      input_tokens: null,
      output_tokens: null,
      cached_input_tokens: null,
      cache_creation_input_tokens: null,
    },
  });
  const value = ledger([simulated]);
  assert.equal(summarizeBilling(value).simulated_count, 1);
  assert.equal(summarizeBilling(value).unknown_count, 0);
  assert.throws(() => confirmed(value, simulated.id, '0'), /Mock/);
  assert.throws(() => confirmed(ledger([entry({ status: 'running' })]), entry().id), /stops/);
});

test('confirmation requires an explicit valid amount, currency and bill reference', () => {
  const value = ledger();
  for (const amount of [
    '-1',
    '1e3',
    '',
    ' ',
    '1.0000001',
    'NaN',
    'Infinity',
    '1,000',
    '1000000000000',
  ]) {
    assert.throws(() => confirmed(value, entry().id, amount));
  }
  assert.throws(() => confirmed(value, entry().id, '1', 'JPY'), /currency/);
  assert.throws(() =>
    confirmEntry(value, entry().id, { amount: '1', currency: 'USD', source: ' ' }),
  );
  assert.throws(
    () => confirmed(value, entry().id, '1', 'USD', { allocation: 'shared', participants: [] }),
    /participant/,
  );
  assert.throws(
    () =>
      confirmed(value, entry().id, '1', 'USD', {
        allocation: 'shared',
        participants: [participants[0], participants[0]],
      }),
    /Duplicate/,
  );
  assert.throws(
    () => confirmed(value, entry().id, '1', 'USD', { allocation: 'owner', participants }),
    /also name/,
  );
  assert.equal(clearConfirmation(confirmed(value, entry().id), entry().id).confirmed.length, 0);
});

test('JSON round trips preserve confirmed and shared evidence and reject a different project', () => {
  let value = confirmed(ledger(), entry().id);
  value = addSharedExpense(
    value,
    {
      id: 'shared-a',
      description: 'Planning',
      amount: '2',
      currency: 'USD',
      source: 'Receipt A',
      participants,
    },
    confirmedAt,
  );
  assert.deepEqual(parseBillingLedger(JSON.parse(exportBillingLedger(value)), 'project'), value);
  assert.throws(() => parseBillingLedger(value, 'other-project'), /different project/);
  assert.throws(() => parseUsageReport(report(), 'other-project'), /different project/);
});

test('malformed, secret-bearing or duplicate reports are rejected without mutating the current ledger', () => {
  const value = confirmed(ledger(), entry().id);
  const before = structuredClone(value);
  const invalid = [
    report([entry(), entry()]),
    report([entry(), entry({ id: 'disguised-duplicate' })]),
    report([entry({ usage: { ...entry().usage, output_tokens: -1 } })]),
    report([entry({ usage: { ...entry().usage, output_tokens: Number.MAX_SAFE_INTEGER + 1 } })]),
    report([entry({ run_id: 'different-run' })]),
    report([entry({ api_key: 'never-store-a-secret' })]),
    report([entry({ owner_name: 'sk-proj-TESTONLY00000000000000000000' })]),
    report([entry({ input_content: 'Unnecessary raw prompts' })]),
    report([entry({ started_at: 'yesterday' })]),
  ];
  for (const item of invalid) assert.throws(() => mergeUsageReport(value, item));
  assert.deepEqual(value, before);
  assert.throws(
    () => parseUsageReport({ ...report(), padding: 'x'.repeat(1_048_576) }, 'project'),
    /MiB/,
  );
  assert.throws(
    () => parseUsageReport(report(Array.from({ length: 5_001 }, (_, i) => ({ id: i }))), 'project'),
    /5000/,
  );
});

test('large valid amounts use exact integer arithmetic through grouping and rounding', () => {
  const second = entry({ id: 'run-1:task-2:1', node_id: 'task-2' });
  let value = ledger([entry(), second]);
  value = confirmed(value, entry().id, '999999999999.000001');
  value = confirmed(value, second.id, '999999999999.000001');
  const summary = summarizeBilling(value);
  assert.equal(summary.agents[0].confirmed.USD, '1999999999998.000002');
  assert.equal(summary.currencies[0].settlement, '1999999999998.00');
});

test('CSV exports escape formulas, quotes and line breaks and distinguish estimates from confirmed costs', () => {
  const malicious = entry({
    owner_name: '=HYPERLINK("https://example.test")',
    node_label: 'A,"quoted"\nline',
    estimated_cost: { amount: '0.1', currency: 'USD', source: 'CLI estimate' },
  });
  let value = confirmed(ledger([malicious]), malicious.id, '0.2');
  value = addSharedExpense(
    value,
    {
      id: 'shared-csv',
      description: '=1+1',
      amount: '0.01',
      currency: 'USD',
      source: '@invoice',
      participants,
    },
    confirmedAt,
  );
  const detail = ledgerEntriesCsv(value);
  assert.match(detail, /"'=HYPERLINK\(""https:\/\/example.test""\)"/);
  assert.match(detail, /"A,""quoted""\nline"/);
  assert.match(detail, /"'@invoice"/);
  assert.match(detail, /"confirmed_amount"/);
  assert.match(detail, /"estimated_amount"/);
  assert.match(settlementCsv(value), /"'=HYPERLINK/);
  assert.match(settlementCsv(value), /"settlement_amount"/);
});
