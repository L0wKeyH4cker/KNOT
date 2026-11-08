import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const configured = JSON.parse(
  readFileSync(new URL('../fixtures/owner-workflow.json', import.meta.url), 'utf8'),
);
const refs = configured.project.members.map((member: any) => member.connection.credential_ref);

async function setup(
  page: Page,
  options: {
    allowed?: boolean;
    credentials?: Record<string, boolean>;
    exportFailure?: { error: string; issues: unknown[] };
  },
) {
  const statuses = { ...options.credentials };
  const saved: Record<string, string> = {};
  const exports: any[] = [];
  const unexpected: string[] = [];
  // All endpoints are fixtures. Never write dummy keys to the user's local server.
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/health')
      return route.fulfill({
        json: {
          ok: true,
          planner_credentials: statuses,
          ...(options.allowed === undefined ? {} : { credential_export_allowed: options.allowed }),
        },
      });
    if (path === '/api/credentials') {
      const { credential_ref, key } = route.request().postDataJSON();
      saved[credential_ref] = key;
      statuses[credential_ref] = true;
      return route.fulfill({ json: { credentials: statuses } });
    }
    if (path === '/api/validate') return route.fulfill({ json: { issues: [] } });
    if (path === '/api/export') {
      exports.push(route.request().postDataJSON());
      if (options.exportFailure) return route.fulfill({ status: 400, json: options.exportFailure });
      return route.fulfill({ contentType: 'application/zip', body: 'fixture-zip-bytes' });
    }
    unexpected.push(path);
    return route.abort();
  });
  await page.addInitScript((workflow) => {
    localStorage.setItem('knot.current.v1', JSON.stringify(workflow));
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' }));
  }, configured);
  return { saved, exports, unexpected };
}

async function openExport(page: Page) {
  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  await page.getByLabel('Run with', { exact: true }).selectOption('opencode');
  await expect(
    page.getByRole('button', { name: 'Download agent workspace', exact: true }),
  ).toBeEnabled();
}

test('local personal export defaults to saved keys and can switch to a shareable package', async ({
  page,
}) => {
  const fixture = await setup(page, { allowed: true });
  await page.goto('/#/workspace/project');
  for (let index = 0; index < 2; index++) {
    const member = configured.project.members[index];
    const card = page.getByRole('article', { name: `Member ${index + 1} settings`, exact: true });
    await card
      .getByRole('button', { name: `Configure connection for ${member.name}`, exact: true })
      .click();
    await card
      .getByLabel('API key', { exact: true })
      .fill(`fixture_private_export_member_${index + 1}`);
    await card.getByRole('button', { name: 'Save on this device', exact: true }).click();
    await expect(card.getByLabel('API key', { exact: true })).toHaveValue('');
  }
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await openExport(page);
  const include = page.getByRole('checkbox', {
    name: 'Include saved member API keys',
    exact: true,
  });
  await expect(include).toBeChecked();
  await expect(page.getByText(/The ZIP contains plain-text keys/)).toBeVisible();
  const artifactDir = resolve('artifacts/owner-opencode');
  mkdirSync(artifactDir, { recursive: true });
  await include.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(artifactDir, 'personal-export.png'), fullPage: true });
  const personalEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  expect((await personalEvent).suggestedFilename()).toBe('knot-personal-workspace.zip');
  await expect(page.getByText(/no key entry is needed/)).toBeVisible();
  expect(fixture.exports[0].include_member_credentials).toBe(true);

  await page.getByRole('button', { name: 'Back to canvas', exact: true }).click();
  await openExport(page);
  await include.uncheck();
  await expect(page.getByText(/Shareable package: no API keys are included/)).toBeVisible();
  const sharedEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  expect((await sharedEvent).suggestedFilename()).not.toBe('knot-personal-workspace.zip');
  expect(fixture.exports[1].include_member_credentials).toBe(false);
  await expect(page.getByText(/Copy .env.example to .env and fill in/)).toBeVisible();
  await expect(page.getByText(/no key entry is needed/)).toHaveCount(0);
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  for (const key of Object.values(fixture.saved)) {
    expect(storage).not.toContain(key);
    expect(JSON.stringify(fixture.exports)).not.toContain(key);
  }
  expect(storage).not.toContain('include_member_credentials');
  expect(
    fixture.exports.map((value) =>
      value.workflow.project.members.map((member: any) => member.connection.credential_ref),
    ),
  ).toEqual([refs, refs]);
  expect(fixture.unexpected).toEqual([]);
});

for (const allowed of [false, undefined]) {
  test(`personal export is unavailable when health permission is ${String(allowed)}`, async ({
    page,
  }) => {
    const fixture = await setup(page, { allowed });
    await page.goto('/#/workspace');
    await openExport(page);
    const include = page.getByRole('checkbox', {
      name: 'Include saved member API keys',
      exact: true,
    });
    await expect(include).toBeDisabled();
    await expect(include).not.toBeChecked();
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
    await download;
    expect(fixture.exports[0].include_member_credentials).toBe(false);
    expect(fixture.unexpected).toEqual([]);
  });
}

test('personal export identifies a member whose key is known to be missing', async ({ page }) => {
  const fixture = await setup(page, {
    allowed: true,
    credentials: { [refs[0]]: true, [refs[1]]: false },
  });
  await page.goto('/#/workspace');
  await openExport(page);
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await expect(page).toHaveURL(/#\/workspace\/check$/);
  await expect(page.getByText(/Bob.*enter an API key and click Save on this device/)).toBeVisible();
  expect(fixture.exports).toHaveLength(0);
  expect(fixture.unexpected).toEqual([]);
});

test('a missing saved key from the export API shows the member issue without downloading', async ({
  page,
}) => {
  const fixture = await setup(page, {
    allowed: true,
    credentials: { [refs[0]]: true, [refs[1]]: true },
    exportFailure: {
      error: 'A saved member key is missing.',
      issues: [
        {
          severity: 'error',
          code: 'owner_credential_not_saved',
          node_id: 'bob-write',
          message: 'Bob: enter a key and click Save on this device in Team members.',
        },
      ],
    },
  });
  let downloaded = false;
  page.on('download', () => {
    downloaded = true;
  });
  await page.goto('/#/workspace');
  await openExport(page);
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await expect(page).toHaveURL(/#\/workspace\/check$/);
  await expect(page.getByText(/Bob.*enter a key and click Save on this device/)).toBeVisible();
  expect(fixture.exports).toHaveLength(1);
  expect(fixture.exports[0].include_member_credentials).toBe(true);
  expect(downloaded).toBe(false);
  await expect(page.getByText('Your agents have their assignments.', { exact: true })).toHaveCount(
    0,
  );
});
