import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const template = JSON.parse(
  readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
);

async function seed(page: Page, workflow = template) {
  await page.addInitScript((workflow) => {
    if (sessionStorage.getItem('owner-fixture-seeded')) return;
    localStorage.setItem('knot.current.v1', JSON.stringify(workflow));
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' }));
    sessionStorage.setItem('owner-fixture-seeded', 'yes');
  }, workflow);
}

test('members save separate keys, retain their connections, and export OpenCode by task owner', async ({
  page,
}) => {
  const saved: Record<string, string> = {};
  let exported: any;
  const unexpected: string[] = [];
  // All APIs are fixtures. This test never stores real credentials or calls models.
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/health')
      return route.fulfill({
        json: {
          ok: true,
          planner_credentials: Object.fromEntries(Object.keys(saved).map((key) => [key, true])),
        },
      });
    if (path === '/api/credentials') {
      const { credential_ref, key } = route.request().postDataJSON();
      saved[credential_ref] = key;
      return route.fulfill({
        json: { credentials: Object.fromEntries(Object.keys(saved).map((key) => [key, true])) },
      });
    }
    if (path === '/api/validate') {
      expect(route.request().postDataJSON().execution).toEqual({ backend: 'opencode', model: '' });
      return route.fulfill({ json: { issues: [] } });
    }
    if (path === '/api/export') {
      exported = route.request().postDataJSON();
      return route.fulfill({ contentType: 'application/zip', body: 'fixture-workspace' });
    }
    unexpected.push(path);
    return route.abort();
  });
  await seed(page);
  await page.goto('/#/workspace/project');
  const refs: string[] = [];
  for (let index = 0; index < 3; index++) {
    const card = page.getByRole('article', { name: `Member ${index + 1} settings`, exact: true });
    await card.getByRole('button', { name: /Configure connection for/ }).click();
    await card.getByText('Advanced connection settings', { exact: true }).click();
    const ref = await card.getByLabel('Credential reference', { exact: true }).inputValue();
    refs.push(ref);
    await expect(card.getByLabel('Credential reference', { exact: true })).toHaveAttribute(
      'readonly',
      '',
    );
    if (index === 0) {
      await card.getByLabel('Provider', { exact: true }).selectOption('deepseek');
      await card.getByLabel('Provider', { exact: true }).selectOption('openai');
    } else if (index === 1) {
      await card.getByLabel('Provider', { exact: true }).selectOption('anthropic');
    }
    await expect(card.getByLabel('Credential reference', { exact: true })).toHaveValue(ref);
    await card.getByLabel('Model name', { exact: true }).fill(`fixture-owner-${index + 1}`);
    await card.getByLabel('API key', { exact: true }).fill(`fixture_owner_${index + 1}_key`);
    await card.getByRole('button', { name: 'Save on this device', exact: true }).click();
    await expect(card.getByLabel('API key', { exact: true })).toHaveValue('');
  }
  expect(new Set(refs).size).toBe(3);
  expect(Object.keys(saved).sort()).toEqual([...refs].sort());
  await page.getByLabel('Member 1 name', { exact: true }).fill('Alice renamed');
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          JSON.parse(localStorage.getItem('knot.current.v1') || '{}').project?.members?.[0]?.name,
      ),
    )
    .toBe('Alice renamed');
  await page.reload();
  await expect(page.getByLabel('Member 1 name', { exact: true })).toHaveValue('Alice renamed');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByTestId('block-research').click();
  await expect(page.getByLabel('Owner model connection')).toContainText('fixture-owner-1');
  await page.getByLabel('Human owner', { exact: true }).selectOption('member-2');
  await expect(page.getByLabel('Owner model connection')).toContainText('fixture-owner-2');
  await expect(page.getByLabel('Owner model connection')).toContainText(
    'API key saved on this device',
  );
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  await page.getByLabel('Run with', { exact: true }).selectOption('opencode');
  await expect(page.getByLabel('Shared model (optional)', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Task owner connections')).toContainText('fixture-owner-2');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await download;
  expect(exported.execution).toEqual({ backend: 'opencode', model: '' });
  expect(exported.workflow.nodes.find((node: any) => node.id === 'research').config.owner_id).toBe(
    'member-2',
  );
  expect(
    exported.workflow.project.members.map((member: any) => member.connection.credential_ref),
  ).toEqual(refs);
  const browserStorage = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  for (const key of Object.values(saved)) {
    expect(JSON.stringify(exported)).not.toContain(key);
    expect(browserStorage).not.toContain(key);
  }
  expect(unexpected).toEqual([]);
});

test('OpenCode export names unconfigured owners before making an export request', async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/health')
      return route.fulfill({ json: { ok: true, planner_credentials: {} } });
    requests.push(path);
    return route.abort();
  });
  await seed(page);
  await page.goto('/#/workspace/export');
  await page.getByLabel('Run with', { exact: true }).selectOption('opencode');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await expect(page).toHaveURL(/#\/workspace\/check$/);
  await expect(page.getByText(/configure Member A's connection/)).toBeVisible();
  await expect(page.getByText(/configure Member B's connection/)).toBeVisible();
  expect(requests).toEqual([]);
});
