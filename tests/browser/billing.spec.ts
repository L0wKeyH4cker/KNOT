import { test, expect, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';

const workflow = JSON.parse(
  readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
);
workflow.project.id = 'billing-fixture-project';
workflow.project.name = 'Cost split example';
workflow.project.members.forEach(
  (member: any, index: number) => (member.name = ['Maya Chen', 'Leo Patel', 'Sam Rivera'][index]),
);
const key = `knot.billing.v1.${workflow.project.id}`;
const stamp = '2026-11-07T15:00:00.000Z';
const report = {
  kind: 'knot-usage',
  schema_version: '1.0',
  project: { id: workflow.project.id, name: workflow.project.name },
  run_id: 'run-cost-fixture',
  updated_at: stamp,
  entries: [
    {
      id: 'run-cost-fixture:research:1',
      run_id: 'run-cost-fixture',
      node_id: 'research',
      node_label: 'Compare venues',
      agent_id: 'researcher',
      agent_name: 'Logistics agent',
      owner_id: 'member-1',
      owner_name: 'Maya Chen',
      provider: 'claude',
      model: 'fixture-only',
      attempt: 1,
      status: 'succeeded',
      usage_status: 'reported',
      usage: {
        input_tokens: 120,
        output_tokens: 30,
        cached_input_tokens: 20,
        cache_creation_input_tokens: 0,
      },
      estimated_cost: { amount: '0.50', currency: 'USD', source: 'CLI estimate' },
      started_at: stamp,
      updated_at: stamp,
    },
    {
      id: 'run-cost-fixture:analysis:1',
      run_id: 'run-cost-fixture',
      node_id: 'analysis',
      node_label: 'Budget attempt',
      agent_id: 'analyst',
      agent_name: 'Budget agent',
      owner_id: 'member-2',
      owner_name: 'Leo Patel',
      provider: 'openai',
      model: 'fixture-only',
      attempt: 1,
      status: 'failed',
      usage_status: 'unknown',
      usage: {
        input_tokens: null,
        output_tokens: null,
        cached_input_tokens: null,
        cache_creation_input_tokens: null,
      },
      started_at: stamp,
      updated_at: stamp,
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript((initial) => {
    // Register before the app's listeners so the tests can defer event delivery
    // while checking the separate save-time conflict/deletion guards.
    window.addEventListener('storage', (event) => {
      const blocked = (window as any).__billingBlockedStorageKeys as string[] | '*' | undefined;
      if (blocked === '*' || (event.key !== null && blocked?.includes(event.key)))
        event.stopImmediatePropagation();
    });
    if (!localStorage.getItem('knot.current.v1')) {
      localStorage.setItem('knot.current.v1', JSON.stringify(initial));
      localStorage.setItem('knot.projects.v1', JSON.stringify([initial]));
    }
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' }));
  }, workflow);
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: {} } }),
  );
  await page.route(/\/api\/(?:plan|requirements\/analyze|connection\/test|credentials)$/, (route) =>
    route.abort(),
  );
});

async function open(page: Page) {
  await page.goto('/#/workspace/costs');
  await expect(page.getByRole('region', { name: 'Costs & split', exact: true })).toBeVisible();
}
async function importReport(page: Page, value: unknown = report) {
  await page.getByLabel('Usage report JSON', { exact: true }).setInputFiles({
    name: 'usage-report.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(value)),
  });
}
async function ledgerExport(page: Page) {
  const event = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export ledger JSON', exact: true }).click();
  return JSON.parse(readFileSync((await (await event).path())!, 'utf8'));
}
async function confirmCost(page: Page, task: string, amount: string, shared = false) {
  await page
    .getByRole('button', { name: `Confirm cost for ${task} attempt 1`, exact: true })
    .click();
  const form = page.getByRole('form', { name: 'Confirm execution cost', exact: true });
  await expect(form.getByLabel('Confirmed amount', { exact: true })).toBeFocused();
  await form.getByLabel('Confirmed amount', { exact: true }).fill(amount);
  await form.getByLabel('Bill reference', { exact: true }).fill(`Invoice checked for ${task}`);
  if (shared) await form.getByLabel('Cost allocation', { exact: true }).selectOption('shared');
  await form.getByRole('button', { name: 'Confirm amount', exact: true }).click();
}

test('usage imports keep estimates separate, preserve failed costs, split shared cents and survive repeat imports and refresh', async ({
  page,
}) => {
  await open(page);
  await importReport(page);
  const details = page.getByRole('table', { name: 'Execution cost details', exact: true });
  await expect(details.getByText('Not confirmed', { exact: true })).toHaveCount(2);
  await expect(page.getByRole('table', { name: 'Member cost split', exact: true })).toHaveCount(0);
  await expect(details.getByText('CLI estimate', { exact: true })).toBeVisible();
  await confirmCost(page, 'Compare venues', '1.00');
  await confirmCost(page, 'Budget attempt', '2.00');
  await page.getByRole('button', { name: 'Add shared cost', exact: true }).click();
  const shared = page.getByRole('form', { name: 'Add shared cost', exact: true });
  await shared.getByLabel('Shared cost description', { exact: true }).fill('Planning');
  await shared.getByLabel('Shared cost amount', { exact: true }).fill('0.01');
  await shared.getByLabel('Shared cost bill reference', { exact: true }).fill('Shared invoice 1');
  await shared.getByRole('button', { name: 'Confirm shared cost', exact: true }).click();
  const split = page.getByRole('table', { name: 'Member cost split', exact: true });
  await expect(
    split.getByRole('row').filter({ hasText: 'Maya Chen' }).getByRole('cell').last(),
  ).toHaveText('1.01');
  await expect(
    split.getByRole('row').filter({ hasText: 'Leo Patel' }).getByRole('cell').last(),
  ).toHaveText('2.00');
  await expect(split.locator('tfoot')).toContainText('3.01');
  const before = await ledgerExport(page);
  await importReport(page);
  const after = await ledgerExport(page);
  expect(after.entries).toEqual(before.entries);
  expect(after.confirmed).toEqual(before.confirmed);
  expect(after.shared).toEqual(before.shared);
  await page.reload();
  await expect(split.locator('tfoot')).toContainText('3.01');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export split CSV', exact: true }).click();
  const csv = readFileSync((await (await download).path())!, 'utf8');
  expect(csv).toContain('Maya Chen');
  expect(csv).toContain('1.01');
  mkdirSync('artifacts/browser', { recursive: true });
  await page.screenshot({
    path: 'artifacts/browser/cost-ledger.png',
    fullPage: true,
    animations: 'disabled',
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: 'artifacts/browser/cost-ledger-mobile.png',
    fullPage: true,
    animations: 'disabled',
  });
});

test('an agent cost can be shared and updated usage requires reconfirmation before it reenters settlement', async ({
  page,
}) => {
  await open(page);
  await importReport(page);
  await confirmCost(page, 'Compare venues', '0.03', true);
  const split = page.getByRole('table', { name: 'Member cost split', exact: true });
  for (const name of ['Maya Chen', 'Leo Patel', 'Sam Rivera'])
    await expect(
      split.getByRole('row').filter({ hasText: name }).getByRole('cell').last(),
    ).toHaveText('0.01');
  const newer = structuredClone(report);
  newer.updated_at = '2026-11-07T16:00:00.000Z';
  newer.entries[0].updated_at = newer.updated_at;
  newer.entries[0].usage.input_tokens = 200;
  await importReport(page, newer);
  await expect(page.getByText('Needs review · excluded from split', { exact: true })).toBeVisible();
  const saved = await ledgerExport(page);
  expect(saved.confirmed[0].needs_review).toBe(true);
  await page
    .getByRole('button', { name: 'Edit confirmed cost for Compare venues attempt 1', exact: true })
    .click();
  const editor = page.getByRole('form', { name: 'Confirm execution cost', exact: true });
  await expect(editor).toBeInViewport();
  await expect(editor.getByLabel('Confirmed amount', { exact: true })).toBeFocused();
  mkdirSync('artifacts/browser', { recursive: true });
  await page.screenshot({
    path: 'artifacts/browser/cost-ledger-editor.png',
    animations: 'disabled',
  });
  await page
    .getByRole('form', { name: 'Confirm execution cost', exact: true })
    .getByRole('button', { name: 'Confirm amount', exact: true })
    .click();
  await expect(split.locator('tfoot')).toContainText('0.03');
  await page
    .getByRole('button', { name: 'Edit confirmed cost for Compare venues attempt 1', exact: true })
    .click();
  await page.getByRole('button', { name: 'Remove confirmation', exact: true }).click();
  await page
    .getByRole('group', { name: 'Remove cost confirmation', exact: true })
    .getByRole('button', { name: 'Cancel', exact: true })
    .click();
  expect((await ledgerExport(page)).confirmed).toHaveLength(1);
  await page.getByRole('button', { name: 'Remove confirmation', exact: true }).click();
  await page.getByRole('button', { name: 'Remove from split', exact: true }).click();
  expect((await ledgerExport(page)).confirmed).toHaveLength(0);
});

test('bad files and another project cannot replace the saved ledger, and corrupt saved data requires explicit recovery', async ({
  page,
}) => {
  await page.addInitScript((storageKey) => {
    localStorage.setItem(storageKey, '{broken ledger');
  }, key);
  await open(page);
  await expect(page.getByText(/The saved ledger could not be read/)).toBeVisible();
  await importReport(page, { ...report, project: { ...report.project, id: 'other-project' } });
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(
    '{broken ledger',
  );
  await importReport(page);
  const recovery = page.getByRole('group', { name: 'Replace ledger confirmation', exact: true });
  await expect(recovery).toBeVisible();
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(
    '{broken ledger',
  );
  await recovery.getByRole('button', { name: 'Replace ledger', exact: true }).click();
  expect((await ledgerExport(page)).entries).toHaveLength(2);
  const stored = await page.evaluate((storageKey) => localStorage.getItem(storageKey), key);
  await page.getByLabel('Usage report JSON', { exact: true }).setInputFiles({
    name: 'bad.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{malformed'),
  });
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(stored);
});

test('a failed storage write retains the current ledger for export and can be retried', async ({
  page,
}) => {
  await open(page);
  await page.evaluate((storageKey) => {
    const saved = Storage.prototype.setItem;
    (window as any).__billingSetItem = saved;
    Storage.prototype.setItem = function (name, value) {
      if (name === storageKey) throw new DOMException('Quota full', 'QuotaExceededError');
      return saved.call(this, name, value);
    };
  }, key);
  await importReport(page);
  await expect(page.getByText('Not saved on this device', { exact: true })).toBeVisible();
  expect((await ledgerExport(page)).entries).toHaveLength(2);
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull();
  await page.evaluate(() => {
    Storage.prototype.setItem = (window as any).__billingSetItem;
  });
  await page.getByRole('button', { name: 'Retry saving', exact: true }).click();
  await expect(page.getByText('Saved on this device', { exact: true }).last()).toBeVisible();
  await page.reload();
  expect((await ledgerExport(page)).entries).toHaveLength(2);
});

test('tabs synchronize costs, and delayed storage events cannot overwrite newer saved confirmations', async ({
  page,
  context,
}) => {
  await open(page);
  await importReport(page);
  const second = await context.newPage();
  await second.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: {} } }),
  );
  await open(second);
  await confirmCost(page, 'Compare venues', '1.00');
  await expect(
    second.getByRole('table', { name: 'Member cost split', exact: true }).locator('tfoot'),
  ).toContainText('1.00');
  await expect(second.getByText('Costs updated from another tab.', { exact: true })).toBeVisible();

  // Keep this page's rendered ledger stale to exercise the save-time check,
  // independently of the normal storage-event synchronization above.
  await page.evaluate((storageKey) => {
    (window as any).__billingBlockedStorageKeys = [storageKey];
  }, key);
  await confirmCost(second, 'Budget attempt', '2.00');
  const committed = await second.evaluate((storageKey) => localStorage.getItem(storageKey), key);
  await page
    .getByRole('button', { name: 'Edit confirmed cost for Compare venues attempt 1', exact: true })
    .click();
  const editor = page.getByRole('form', { name: 'Confirm execution cost', exact: true });
  await editor.getByLabel('Confirmed amount', { exact: true }).fill('3.00');
  await editor.getByRole('button', { name: 'Confirm amount', exact: true }).click();
  await expect(page.getByText(/The saved ledger changed in another tab/)).toBeVisible();
  await expect(page.getByText('Not saved on this device', { exact: true })).toBeVisible();
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(
    committed,
  );

  const unsaved = await ledgerExport(page);
  expect(unsaved.confirmed).toHaveLength(1);
  expect(Number(unsaved.confirmed[0].amount)).toBe(3);
  const saved = await ledgerExport(second);
  expect(saved.confirmed).toHaveLength(2);
  expect(
    Number(saved.confirmed.find((entry: any) => entry.entry_id === report.entries[0].id).amount),
  ).toBe(1);
  await page
    .getByRole('button', { name: 'Discard unsaved edits and reload saved ledger', exact: true })
    .click();
  expect((await ledgerExport(page)).confirmed).toEqual(saved.confirmed);
  await second.close();
});

test('deleting a project prevents a stale cost tab from recreating its ledger and preserves other projects', async ({
  page,
  context,
}) => {
  await open(page);
  await importReport(page);
  const other = structuredClone(workflow);
  other.project.id = 'other-billing-project';
  other.project.name = 'Other cost project';
  const otherKey = `knot.billing.v1.${other.project.id}`;
  const otherLedger = JSON.stringify({
    kind: 'knot-billing',
    schema_version: '1.0',
    project_id: other.project.id,
    revision: 1,
    entries: [],
    confirmed: [],
    shared: [
      {
        id: 'other-shared',
        description: 'Other project planning',
        amount: '8.00',
        currency: 'USD',
        source: 'Other invoice',
        participants: [{ id: 'other-owner', name: 'Other owner' }],
        confirmed_at: stamp,
      },
    ],
  });
  await page.evaluate(
    ({ original, extra, ledgerKey, ledger }) => {
      localStorage.setItem('knot.projects.v1', JSON.stringify([original, extra]));
      localStorage.setItem(ledgerKey, ledger);
      // Simulate a tab whose event delivery has stalled. Saving must still check
      // the deletion tombstone directly before creating any storage record.
      (window as any).__billingBlockedStorageKeys = '*';
    },
    { original: workflow, extra: other, ledgerKey: otherKey, ledger: otherLedger },
  );
  const library = await context.newPage();
  await library.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: {} } }),
  );
  await library.goto('/#/projects');
  await library.getByRole('button', { name: 'Delete Cost split example', exact: true }).click();
  await library
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Delete project', exact: true })
    .click();
  await expect(
    library.getByRole('link', { name: 'Open Other cost project in a new tab', exact: true }),
  ).toBeVisible();
  await expect(
    library.getByRole('link', { name: 'Open Cost split example in a new tab', exact: true }),
  ).toHaveCount(0);
  expect(await library.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull();

  await confirmCost(page, 'Compare venues', '1.00');
  await expect(page.getByText(/This project was deleted\. Export your ledger/)).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Import usage report', exact: true }),
  ).toBeDisabled();
  expect((await ledgerExport(page)).confirmed).toHaveLength(1);
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull();
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), otherKey)).toBe(
    otherLedger,
  );
  await library.close();
});

test('historical shared participants remain editable but new costs default to current project members', async ({
  page,
}) => {
  await open(page);
  const historical = {
    kind: 'knot-billing',
    schema_version: '1.0',
    project_id: workflow.project.id,
    revision: 1,
    entries: report.entries,
    shared: [],
    confirmed: [
      {
        entry_id: report.entries[0].id,
        amount: '0.02',
        currency: 'USD',
        source: 'Historical invoice',
        confirmed_at: stamp,
        needs_review: false,
        allocation: 'shared',
        participants: [
          { id: 'member-1', name: 'Maya Chen' },
          { id: 'former-member', name: 'Former teammate' },
        ],
      },
    ],
  };
  await page.getByLabel('Ledger JSON', { exact: true }).setInputFiles({
    name: 'historical-ledger.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(historical)),
  });
  await page
    .getByRole('button', { name: 'Edit confirmed cost for Compare venues attempt 1', exact: true })
    .click();
  const editor = page.getByRole('form', { name: 'Confirm execution cost', exact: true });
  await expect(
    editor.getByRole('checkbox', { name: 'Former teammate', exact: true }),
  ).toBeChecked();
  await expect(editor.getByRole('checkbox', { name: 'Maya Chen', exact: true })).toBeChecked();
  await expect(editor.getByRole('checkbox', { name: 'Leo Patel', exact: true })).not.toBeChecked();
  // Reopening the same active row brings the amount field back into focus.
  await editor.getByLabel('Bill reference', { exact: true }).focus();
  await page
    .getByRole('button', { name: 'Edit confirmed cost for Compare venues attempt 1', exact: true })
    .click();
  await expect(editor.getByLabel('Confirmed amount', { exact: true })).toBeFocused();
  await editor.getByRole('button', { name: 'Confirm amount', exact: true }).click();
  expect((await ledgerExport(page)).confirmed[0].participants).toEqual(
    historical.confirmed[0].participants,
  );

  await page.getByRole('button', { name: 'Add shared cost', exact: true }).click();
  const shared = page.getByRole('form', { name: 'Add shared cost', exact: true });
  await expect(shared.getByLabel('Shared cost description', { exact: true })).toBeFocused();
  await expect(
    shared.getByRole('checkbox', { name: 'Former teammate', exact: true }),
  ).not.toBeChecked();
  for (const name of ['Maya Chen', 'Leo Patel', 'Sam Rivera'])
    await expect(shared.getByRole('checkbox', { name, exact: true })).toBeChecked();
  await shared.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page
    .getByRole('button', { name: 'Confirm cost for Budget attempt attempt 1', exact: true })
    .click();
  await editor.getByLabel('Cost allocation', { exact: true }).selectOption('shared');
  await expect(
    editor.getByRole('checkbox', { name: 'Former teammate', exact: true }),
  ).not.toBeChecked();
  for (const name of ['Maya Chen', 'Leo Patel', 'Sam Rivera'])
    await expect(editor.getByRole('checkbox', { name, exact: true })).toBeChecked();
});
