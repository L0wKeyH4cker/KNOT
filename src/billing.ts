import { assertSafeWorkflow } from './model.ts';

export type Currency = 'USD' | 'CNY' | 'EUR' | 'GBP';
export const BILLING_CURRENCIES: Currency[] = ['USD', 'CNY', 'EUR', 'GBP'];
export type UsageEntry = {
  id: string;
  run_id: string;
  node_id: string;
  node_label: string;
  agent_id: string;
  agent_name: string;
  owner_id: string;
  owner_name: string;
  provider: string;
  model: string;
  attempt: number;
  status: 'running' | 'succeeded' | 'failed' | 'unknown';
  usage_status: 'reported' | 'partial' | 'unknown' | 'simulated' | 'legacy';
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    cached_input_tokens: number | null;
    cache_creation_input_tokens: number | null;
  };
  started_at: string;
  updated_at: string;
  estimated_cost?: { amount: string; currency: 'USD'; source: string };
};
export type UsageReport = {
  kind: 'knot-usage';
  schema_version: '1.0';
  project: { id: string; name: string };
  run_id: string;
  updated_at: string;
  entries: UsageEntry[];
};
export type Confirmation = {
  entry_id: string;
  amount: string;
  currency: Currency;
  source: string;
  confirmed_at: string;
  allocation: 'owner' | 'shared';
  participants: Participant[];
  needs_review: boolean;
};
export type Participant = { id: string; name: string };
export type SharedExpense = {
  id: string;
  description: string;
  amount: string;
  currency: Currency;
  source: string;
  participants: Participant[];
  confirmed_at: string;
};
export type BillingLedger = {
  kind: 'knot-billing';
  schema_version: '1.0';
  project_id: string;
  revision: number;
  entries: UsageEntry[];
  confirmed: Confirmation[];
  shared: SharedExpense[];
};
export type AgentCostSummary = {
  agent_id: string;
  agent_name: string;
  owner_id: string;
  owner_name: string;
  entry_count: number;
  unknown_count: number;
  partial_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  confirmed: Partial<Record<Currency, string>>;
  estimated: Partial<Record<Currency, string>>;
};
export type MemberSettlement = {
  id: string;
  name: string;
  currency: Currency;
  direct: string;
  shared: string;
  total: string;
};
export type BillingSummary = {
  agents: AgentCostSummary[];
  members: MemberSettlement[];
  currencies: { currency: Currency; confirmed: string; estimated: string; settlement: string }[];
  unknown_count: number;
  partial_count: number;
  simulated_count: number;
  review_count: number;
};

const MAX_ENTRIES = 5_000;
const MAX_REPORT_BYTES = 1_048_576;
const MAX_LEDGER_BYTES = 8_388_608;
const MICRO = 1_000_000n;
const CENT = 10_000n;
const usageKeys = [
  'input_tokens',
  'output_tokens',
  'cached_input_tokens',
  'cache_creation_input_tokens',
] as const;

function record(
  value: unknown,
  required: string[],
  optional: string[] = [],
): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('Expected a JSON object.');
  const object = value as Record<string, unknown>;
  if (
    required.some((key) => !Object.hasOwn(object, key)) ||
    Object.keys(object).some((key) => !required.includes(key) && !optional.includes(key))
  )
    throw Error('The billing file contains missing or unsupported fields.');
  return object;
}

function text(value: unknown, label: string, limit = 300, allowEmpty = false): string {
  if (
    typeof value !== 'string' ||
    (!allowEmpty && !value.trim()) ||
    value.length > limit ||
    /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)
  )
    throw Error(`${label} must be valid text of at most ${limit} characters.`);
  return value;
}

function date(value: unknown): string {
  const result = text(value, 'Timestamp', 40);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(result) ||
    !Number.isFinite(Date.parse(result))
  )
    throw Error('Billing timestamps must be valid ISO dates with a timezone.');
  const calendar = new Date(`${result.slice(0, 10)}T00:00:00Z`);
  if (
    calendar.toISOString().slice(0, 10) !== result.slice(0, 10) ||
    Number(result.slice(11, 13)) > 23 ||
    Number(result.slice(14, 16)) > 59 ||
    Number(result.slice(17, 19)) > 59
  )
    throw Error('Billing timestamps must use a valid calendar date and time.');
  return result;
}

// The runtime emits microseconds. Date.parse alone truncates them and can
// mistake two rapid usage snapshots for the same update.
function timestamp(value: string): bigint {
  const fraction = value.match(/\.(\d{1,6})/)?.[1] || '';
  return BigInt(Date.parse(value)) * 1_000n + BigInt(fraction.padEnd(6, '0').slice(3));
}

function count(value: unknown, label: string, minimum = 0): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum)
    throw Error(`${label} must be a safe whole number of at least ${minimum}.`);
  return value;
}

function oneOf<T extends string>(value: unknown, options: readonly T[], label: string): T {
  if (typeof value !== 'string' || !options.includes(value as T))
    throw Error(`Unsupported ${label}.`);
  return value as T;
}

function currency(value: unknown): Currency {
  return oneOf(value, BILLING_CURRENCIES, 'currency');
}

function micros(value: unknown): bigint {
  if (typeof value !== 'string' || !/^(?:0|[1-9]\d{0,17})(?:\.\d{1,6})?$/.test(value.trim()))
    throw Error('Enter a nonnegative amount with up to six decimal places.');
  const [whole, fraction = ''] = value.trim().split('.');
  return BigInt(whole) * MICRO + BigInt(fraction.padEnd(6, '0'));
}

function amount(value: unknown): string {
  const parsed = micros(value);
  if (parsed > 999_999_999_999_999_999n)
    throw Error('An individual amount must be below one trillion.');
  return formatMicros(parsed);
}

function formatMicros(value: bigint): string {
  const fraction = (value % MICRO).toString().padStart(6, '0').replace(/0+$/, '');
  return `${value / MICRO}${fraction ? `.${fraction}` : ''}`;
}

function formatCents(value: bigint): string {
  return `${value / 100n}.${(value % 100n).toString().padStart(2, '0')}`;
}

function bounded(value: unknown, byteLimit: number): void {
  let encoded: string;
  try {
    encoded = JSON.stringify(value);
  } catch {
    throw Error('Billing data must be serializable JSON.');
  }
  if (typeof encoded !== 'string' || new TextEncoder().encode(encoded).length > byteLimit)
    throw Error(`This billing file exceeds the ${byteLimit / 1_048_576} MiB limit.`);
  assertSafeWorkflow(value);
}

function list(value: unknown, label: string, max = MAX_ENTRIES): unknown[] {
  if (!Array.isArray(value) || value.length > max)
    throw Error(`${label} must contain at most ${max} records.`);
  return value;
}

function unique<T>(items: T[], key: (item: T) => string, label: string): T[] {
  if (new Set(items.map(key)).size !== items.length) throw Error(`Duplicate ${label}.`);
  return items;
}

function usageEntries(value: unknown, label: string): UsageEntry[] {
  return unique(
    unique(list(value, label).map(parseEntry), (entry) => entry.id, 'usage entry ID'),
    (entry) => JSON.stringify([entry.run_id, entry.node_id, entry.attempt]),
    'execution attempt',
  );
}

function parseEntry(value: unknown): UsageEntry {
  const item = record(
    value,
    [
      'id',
      'run_id',
      'node_id',
      'node_label',
      'agent_id',
      'agent_name',
      'owner_id',
      'owner_name',
      'provider',
      'model',
      'attempt',
      'status',
      'usage_status',
      'usage',
      'started_at',
      'updated_at',
    ],
    ['estimated_cost'],
  );
  const sourceUsage = record(item.usage, [...usageKeys]);
  const usage = Object.fromEntries(
    usageKeys.map((key) => [key, sourceUsage[key] === null ? null : count(sourceUsage[key], key)]),
  ) as UsageEntry['usage'];
  if (
    item.usage_status === 'reported' &&
    usage.input_tokens !== null &&
    BigInt(usage.cached_input_tokens ?? 0) + BigInt(usage.cache_creation_input_tokens ?? 0) >
      BigInt(usage.input_tokens)
  )
    throw Error('Cached input tokens cannot exceed total input tokens.');
  const result: UsageEntry = {
    id: text(item.id, 'Entry ID', 512),
    run_id: text(item.run_id, 'Run ID'),
    node_id: text(item.node_id, 'Task ID'),
    node_label: text(item.node_label, 'Task name', 1_000),
    agent_id: text(item.agent_id, 'Agent ID'),
    agent_name: text(item.agent_name, 'Agent name'),
    owner_id: text(item.owner_id, 'Owner ID'),
    owner_name: text(item.owner_name, 'Owner name'),
    provider: text(item.provider, 'Provider', 100, true),
    model: text(item.model, 'Model', 300, true),
    attempt: count(item.attempt, 'Attempt', 1),
    status: oneOf(item.status, ['running', 'succeeded', 'failed', 'unknown'], 'task status'),
    usage_status: oneOf(
      item.usage_status,
      ['reported', 'partial', 'unknown', 'simulated', 'legacy'],
      'usage status',
    ),
    usage,
    started_at: date(item.started_at),
    updated_at: date(item.updated_at),
  };
  if (timestamp(result.updated_at) < timestamp(result.started_at))
    throw Error('An entry cannot be updated before it starts.');
  if (item.estimated_cost !== undefined) {
    const cost = record(item.estimated_cost, ['amount', 'currency', 'source']);
    result.estimated_cost = {
      amount: amount(cost.amount),
      currency: oneOf(cost.currency, ['USD'], 'estimate currency'),
      source: text(cost.source, 'Estimate source', 500),
    };
  }
  if (result.usage_status === 'simulated' && result.estimated_cost)
    throw Error('Simulated runs cannot contain monetary estimates.');
  return result;
}

export function parseUsageReport(value: unknown, projectId: string): UsageReport {
  bounded(value, MAX_REPORT_BYTES);
  const raw = record(value, [
    'kind',
    'schema_version',
    'project',
    'run_id',
    'updated_at',
    'entries',
  ]);
  if (raw.kind !== 'knot-usage' || raw.schema_version !== '1.0')
    throw Error('Choose a KNOT usage-report.json file (version 1.0).');
  const project = record(raw.project, ['id', 'name']);
  if (project.id !== projectId) throw Error('This usage report belongs to a different project.');
  const runId = text(raw.run_id, 'Run ID');
  const entries = usageEntries(raw.entries, 'Usage report');
  if (entries.some((entry) => entry.run_id !== runId))
    throw Error('Every report entry must belong to its stated run.');
  return {
    kind: 'knot-usage',
    schema_version: '1.0',
    project: { id: text(project.id, 'Project ID'), name: text(project.name, 'Project name') },
    run_id: runId,
    updated_at: date(raw.updated_at),
    entries,
  };
}

export function emptyBillingLedger(projectId: string): BillingLedger {
  return {
    kind: 'knot-billing',
    schema_version: '1.0',
    project_id: text(projectId, 'Project ID'),
    revision: 0,
    entries: [],
    confirmed: [],
    shared: [],
  };
}

function parseConfirmation(value: unknown): Confirmation {
  const raw = record(
    value,
    ['entry_id', 'amount', 'currency', 'source', 'confirmed_at'],
    ['allocation', 'participants', 'needs_review'],
  );
  const allocation = oneOf(raw.allocation ?? 'owner', ['owner', 'shared'], 'cost allocation');
  const participants = parseParticipants(raw.participants ?? [], allocation === 'shared');
  if (allocation === 'owner' && participants.length)
    throw Error('Owner costs cannot also name shared participants.');
  if (raw.needs_review !== undefined && typeof raw.needs_review !== 'boolean')
    throw Error('Cost review status must be a boolean.');
  return {
    entry_id: text(raw.entry_id, 'Entry ID', 512),
    amount: amount(raw.amount),
    currency: currency(raw.currency),
    source: text(raw.source, 'Bill reference', 1_000).trim(),
    confirmed_at: date(raw.confirmed_at),
    allocation,
    participants,
    needs_review: raw.needs_review === true,
  };
}

function parseParticipants(value: unknown, required: boolean): Participant[] {
  const participants = unique(
    list(value, 'Shared expense participants', 50).map((item) => {
      const member = record(item, ['id', 'name']);
      return { id: text(member.id, 'Participant ID'), name: text(member.name, 'Participant name') };
    }),
    (member) => member.id,
    'participant',
  );
  if (required && !participants.length)
    throw Error('Choose at least one participant for a shared expense.');
  return participants;
}

function parseShared(value: unknown): SharedExpense {
  const raw = record(value, [
    'id',
    'description',
    'amount',
    'currency',
    'source',
    'participants',
    'confirmed_at',
  ]);
  const participants = parseParticipants(raw.participants, true);
  return {
    id: text(raw.id, 'Shared expense ID'),
    description: text(raw.description, 'Expense description', 1_000).trim(),
    amount: amount(raw.amount),
    currency: currency(raw.currency),
    source: text(raw.source, 'Bill reference', 1_000).trim(),
    participants,
    confirmed_at: date(raw.confirmed_at),
  };
}

export function parseBillingLedger(value: unknown, projectId: string): BillingLedger {
  bounded(value, MAX_LEDGER_BYTES);
  const raw = record(value, [
    'kind',
    'schema_version',
    'project_id',
    'revision',
    'entries',
    'confirmed',
    'shared',
  ]);
  if (raw.kind !== 'knot-billing' || raw.schema_version !== '1.0')
    throw Error('Choose a KNOT billing ledger (version 1.0).');
  if (raw.project_id !== projectId)
    throw Error('This billing ledger belongs to a different project.');
  const entries = usageEntries(raw.entries, 'Ledger');
  const confirmed = unique(
    list(raw.confirmed, 'Confirmations').map(parseConfirmation),
    (entry) => entry.entry_id,
    'confirmation',
  );
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  if (
    confirmed.some(
      (charge) =>
        !byId.has(charge.entry_id) || byId.get(charge.entry_id)!.usage_status === 'simulated',
    )
  )
    throw Error('Confirmed fees must reference an existing, non-simulated execution.');
  if (
    confirmed.some(
      (charge) => byId.get(charge.entry_id)!.status === 'running' && !charge.needs_review,
    )
  )
    throw Error('A running execution cannot have a settled fee. Mark it for review first.');
  const shared = unique(
    list(raw.shared, 'Shared expenses', 1_000).map(parseShared),
    (item) => item.id,
    'shared expense ID',
  );
  return {
    kind: 'knot-billing',
    schema_version: '1.0',
    project_id: text(raw.project_id, 'Project ID'),
    revision: count(raw.revision, 'Ledger revision'),
    entries,
    confirmed,
    shared,
  };
}

function revised(ledger: BillingLedger, changes: Partial<BillingLedger>): BillingLedger {
  if (ledger.revision >= Number.MAX_SAFE_INTEGER)
    throw Error('This ledger revision cannot be increased.');
  return parseBillingLedger(
    { ...ledger, ...changes, revision: ledger.revision + 1 },
    ledger.project_id,
  );
}

export function mergeUsageReport(ledger: BillingLedger, value: UsageReport): BillingLedger {
  const current = parseBillingLedger(ledger, ledger.project_id);
  const report = parseUsageReport(value, ledger.project_id);
  const entries = new Map(current.entries.map((entry) => [entry.id, entry]));
  const reviewIds = new Set<string>();
  let changed = false;
  for (const incoming of report.entries) {
    const previous = entries.get(incoming.id);
    if (previous) {
      const immutable = [
        'run_id',
        'node_id',
        'agent_id',
        'owner_id',
        'owner_name',
        'agent_name',
        'attempt',
        'started_at',
      ] as const;
      if (immutable.some((key) => previous[key] !== incoming[key]))
        throw Error(
          'A usage entry changed its original execution or responsibility. Import was cancelled.',
        );
      if (timestamp(incoming.updated_at) < timestamp(previous.updated_at)) continue;
      if (timestamp(incoming.updated_at) === timestamp(previous.updated_at)) {
        if (JSON.stringify(previous) !== JSON.stringify(incoming))
          throw Error(
            'Conflicting usage snapshots have the same update time. Import was cancelled.',
          );
        continue;
      }
      if (
        (previous.usage_status === 'simulated' && incoming.usage_status !== 'simulated') ||
        (previous.usage_status !== 'simulated' && incoming.usage_status === 'simulated')
      )
        throw Error('An existing execution cannot change between real and simulated usage.');
      if (JSON.stringify(previous) === JSON.stringify(incoming)) continue;
      if (
        ['usage', 'usage_status', 'estimated_cost', 'provider', 'model', 'status'].some(
          (key) =>
            JSON.stringify(previous[key as keyof UsageEntry]) !==
            JSON.stringify(incoming[key as keyof UsageEntry]),
        )
      )
        reviewIds.add(incoming.id);
    }
    entries.set(incoming.id, incoming);
    changed = true;
  }
  return changed
    ? revised(current, {
        entries: [...entries.values()],
        confirmed: current.confirmed.map((charge) =>
          reviewIds.has(charge.entry_id) ? { ...charge, needs_review: true } : charge,
        ),
      })
    : current;
}

export function confirmEntry(
  ledger: BillingLedger,
  entryId: string,
  input: {
    amount: string;
    currency: Currency;
    source: string;
    allocation?: 'owner' | 'shared';
    participants?: Participant[];
  },
  at = new Date().toISOString(),
): BillingLedger {
  const entry = ledger.entries.find((item) => item.id === entryId);
  if (!entry) throw Error('Choose an imported execution before confirming its cost.');
  if (entry.usage_status === 'simulated')
    throw Error('Mock executions do not create billable costs.');
  if (entry.status === 'running')
    throw Error('Wait until this execution stops before confirming its cost.');
  const confirmation = parseConfirmation({
    entry_id: entryId,
    ...input,
    confirmed_at: at,
    needs_review: false,
  });
  return revised(ledger, {
    confirmed: [...ledger.confirmed.filter((item) => item.entry_id !== entryId), confirmation],
  });
}

export function clearConfirmation(ledger: BillingLedger, entryId: string): BillingLedger {
  return revised(ledger, {
    confirmed: ledger.confirmed.filter((item) => item.entry_id !== entryId),
  });
}

export function addSharedExpense(
  ledger: BillingLedger,
  input: {
    description: string;
    amount: string;
    currency: Currency;
    source: string;
    participants: Participant[];
    id?: string;
  },
  at = new Date().toISOString(),
): BillingLedger {
  const expense = parseShared({
    ...input,
    id: input.id || `shared-${crypto.randomUUID()}`,
    confirmed_at: at,
  });
  if (ledger.shared.some((item) => item.id === expense.id))
    throw Error('This shared expense already exists.');
  return revised(ledger, { shared: [...ledger.shared, expense] });
}

export function removeSharedExpense(ledger: BillingLedger, id: string): BillingLedger {
  return revised(ledger, { shared: ledger.shared.filter((expense) => expense.id !== id) });
}

function sumTokens(a: number | null, b: number | null): number | null {
  return a === null || b === null || !Number.isSafeInteger(a + b) ? null : a + b;
}

function addMoney(target: Partial<Record<Currency, string>>, code: Currency, value: string): void {
  target[code] = formatMicros(micros(target[code] || '0') + micros(value));
}

export function summarizeBilling(value: BillingLedger): BillingSummary {
  const ledger = parseBillingLedger(value, value.project_id);
  const confirmations = new Map(ledger.confirmed.map((charge) => [charge.entry_id, charge]));
  const agents = new Map<string, AgentCostSummary>();
  const totals = new Map<Currency, { confirmed: bigint; estimated: bigint }>();
  const people = new Map<
    string,
    { id: string; name: string; currency: Currency; direct: bigint; shared: bigint }
  >();
  const total = (code: Currency) => {
    if (!totals.has(code)) totals.set(code, { confirmed: 0n, estimated: 0n });
    return totals.get(code)!;
  };
  const person = (member: Participant, code: Currency) => {
    const key = JSON.stringify([code, member.id]);
    if (!people.has(key)) people.set(key, { ...member, currency: code, direct: 0n, shared: 0n });
    return people.get(key)!;
  };
  const share = (participants: Participant[], code: Currency, micro: bigint) => {
    const sorted = [...participants].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const each = micro / BigInt(sorted.length),
      remainder = micro % BigInt(sorted.length);
    sorted.forEach((member, index) => {
      person(member, code).shared += each + (BigInt(index) < remainder ? 1n : 0n);
    });
  };
  let unknown_count = 0,
    partial_count = 0,
    simulated_count = 0;
  for (const entry of ledger.entries) {
    const key = JSON.stringify([entry.agent_id, entry.owner_id]);
    if (!agents.has(key))
      agents.set(key, {
        agent_id: entry.agent_id,
        agent_name: entry.agent_name,
        owner_id: entry.owner_id,
        owner_name: entry.owner_name,
        entry_count: 0,
        unknown_count: 0,
        partial_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        confirmed: {},
        estimated: {},
      });
    const group = agents.get(key)!;
    group.entry_count++;
    group.input_tokens = sumTokens(group.input_tokens, entry.usage.input_tokens);
    group.output_tokens = sumTokens(group.output_tokens, entry.usage.output_tokens);
    if (entry.usage_status === 'partial') {
      partial_count++;
      group.partial_count++;
    }
    if (entry.usage_status === 'simulated') {
      simulated_count++;
      continue;
    }
    const charge = confirmations.get(entry.id);
    if (charge && !charge.needs_review) {
      const micro = micros(charge.amount);
      addMoney(group.confirmed, charge.currency, charge.amount);
      total(charge.currency).confirmed += micro;
      if (charge.allocation === 'shared') share(charge.participants, charge.currency, micro);
      else person({ id: entry.owner_id, name: entry.owner_name }, charge.currency).direct += micro;
    } else if (entry.estimated_cost) {
      const cost = entry.estimated_cost;
      addMoney(group.estimated, cost.currency, cost.amount);
      total(cost.currency).estimated += micros(cost.amount);
    } else {
      unknown_count++;
      group.unknown_count++;
    }
  }
  for (const expense of ledger.shared) {
    const micro = micros(expense.amount);
    share(expense.participants, expense.currency, micro);
    total(expense.currency).confirmed += micro;
  }
  const members: MemberSettlement[] = [];
  const currencies: BillingSummary['currencies'] = [];
  for (const [code, sums] of [...totals].sort(([a], [b]) => a.localeCompare(b))) {
    const due = [...people.values()]
      .filter((item) => item.currency === code)
      .map((member) => {
        const micro = member.direct + member.shared;
        return { ...member, cents: micro / CENT, remainder: micro % CENT };
      });
    const rounded = (sums.confirmed + CENT / 2n) / CENT;
    let remaining = rounded - due.reduce((sum, member) => sum + member.cents, 0n);
    due.sort((a, b) =>
      a.remainder > b.remainder
        ? -1
        : a.remainder < b.remainder
          ? 1
          : a.id < b.id
            ? -1
            : a.id > b.id
              ? 1
              : 0,
    );
    for (const member of due) {
      if (remaining > 0n) {
        member.cents++;
        remaining--;
      }
    }
    if (remaining !== 0n) throw Error('The settlement could not preserve its total.');
    members.push(
      ...due
        .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
        .map((member) => ({
          id: member.id,
          name: member.name,
          currency: code,
          direct: formatMicros(member.direct),
          shared: formatMicros(member.shared),
          total: formatCents(member.cents),
        })),
    );
    currencies.push({
      currency: code,
      confirmed: formatMicros(sums.confirmed),
      estimated: formatMicros(sums.estimated),
      settlement: formatCents(rounded),
    });
  }
  return {
    agents: [...agents.values()],
    members,
    currencies,
    unknown_count,
    partial_count,
    simulated_count,
    review_count: ledger.confirmed.filter((charge) => charge.needs_review).length,
  };
}

function csv(rows: unknown[][]): string {
  const cell = (value: unknown) => {
    let result = value === null || value === undefined ? '' : String(value);
    if (/^[\s]*[=+\-@]/.test(result) || /^[\t\r\n]/.test(result)) result = `'${result}`;
    return `"${result.replaceAll('"', '""')}"`;
  };
  return '\uFEFF' + rows.map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n';
}

export function ledgerEntriesCsv(value: BillingLedger): string {
  const ledger = parseBillingLedger(value, value.project_id);
  const confirmed = new Map(ledger.confirmed.map((item) => [item.entry_id, item]));
  const rows: unknown[][] = [
    [
      'record_type',
      'entry_id',
      'run_id',
      'task_id',
      'task',
      'agent_id',
      'agent',
      'member_id',
      'member',
      'attempt',
      'status',
      'usage_status',
      ...usageKeys,
      'cost_status',
      'confirmed_amount',
      'confirmed_currency',
      'bill_reference',
      'confirmed_at',
      'estimated_amount',
      'estimated_currency',
      'estimate_source',
      'participants',
      'started_at',
      'updated_at',
      'allocation',
    ],
  ];
  for (const entry of ledger.entries) {
    const charge = confirmed.get(entry.id);
    rows.push([
      'execution',
      entry.id,
      entry.run_id,
      entry.node_id,
      entry.node_label,
      entry.agent_id,
      entry.agent_name,
      entry.owner_id,
      entry.owner_name,
      entry.attempt,
      entry.status,
      entry.usage_status,
      ...usageKeys.map((key) => entry.usage[key]),
      entry.usage_status === 'simulated'
        ? 'simulated'
        : charge?.needs_review
          ? 'needs_review'
          : charge
            ? 'confirmed'
            : entry.estimated_cost
              ? 'estimated'
              : 'unknown',
      charge?.amount,
      charge?.currency,
      charge?.source,
      charge?.confirmed_at,
      entry.estimated_cost?.amount,
      entry.estimated_cost?.currency,
      entry.estimated_cost?.source,
      charge?.participants.map((member) => `${member.id}: ${member.name}`).join('; '),
      entry.started_at,
      entry.updated_at,
      charge?.allocation,
    ]);
  }
  for (const expense of ledger.shared) {
    rows.push([
      'shared',
      expense.id,
      '',
      '',
      expense.description,
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      'confirmed',
      expense.amount,
      expense.currency,
      expense.source,
      expense.confirmed_at,
      '',
      '',
      '',
      expense.participants.map((member) => `${member.id}: ${member.name}`).join('; '),
      '',
      '',
      'shared',
    ]);
  }
  return csv(rows);
}

export function settlementCsv(ledger: BillingLedger): string {
  return csv([
    ['member_id', 'member', 'currency', 'direct_amount', 'shared_amount', 'settlement_amount'],
    ...summarizeBilling(ledger).members.map((member) => [
      member.id,
      member.name,
      member.currency,
      member.direct,
      member.shared,
      member.total,
    ]),
  ]);
}

export function exportBillingLedger(ledger: BillingLedger): string {
  // Keep the file within the same byte limit used for validation/import; pretty
  // printing could otherwise produce a backup that this app cannot read back.
  return JSON.stringify(parseBillingLedger(ledger, ledger.project_id));
}
