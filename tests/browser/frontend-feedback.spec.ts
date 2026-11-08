import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const example = JSON.parse(
  readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
);

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: { OPENAI_API_KEY: true } } }),
  );
  // Every model request in this suite stays local to the browser fixtures.
  await page.route(/\/api\/(?:plan|requirements\/analyze|connection\/test)$/, (route) =>
    route.abort(),
  );
});

test('project setup shows required markers and English validation before creating a valid project', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Continue to project setup' }).click();
  await expect(page.locator('.required-mark')).toHaveCount(4);
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByText('Please enter a project name.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Project name', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Final deliverable', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await page.getByLabel('Project name', { exact: true }).fill('  Feedback project  ');
  await page.getByLabel('Final deliverable', { exact: true }).fill('report.md');
  await page.getByLabel('What are you working on?', { exact: true }).fill('Prepare a report.');
  for (const value of ['0', '51', '1.5', '']) {
    await page.getByLabel('Team size', { exact: true }).fill(value);
    await page.getByRole('button', { name: 'Create project', exact: true }).click();
    await expect(page.getByText('Team size must be a whole number from 1 to 50.')).toBeVisible();
    await expect(page.getByLabel('Team size', { exact: true })).toBeFocused();
  }
  await page.getByLabel('Team size', { exact: true }).fill('2');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'How would you like to start?' })).toBeVisible();
});

test('slow generation shows reassurance after eight seconds and clears it on completion', async ({
  page,
}) => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route('**/api/plan', async (route) => {
    await pending;
    await route.fulfill({ json: { workflow: example } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Upload project requirements' }).click();
  await page.getByLabel('Project goal', { exact: true }).fill('Prepare a report.');
  await page.getByLabel('Expected deliverables', { exact: true }).fill('report.md');
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.clock.install({ time: new Date('2026-11-07T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-07T12:00:01Z'));
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await page.clock.fastForward(7999);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toHaveCount(0);
  await page.clock.fastForward(1);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Still working on it', { exact: true })).toBeVisible();
  finish();
  await expect(page.locator('.block-card')).toHaveCount(example.nodes.length);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toHaveCount(0);
});

test('connection wait can be dismissed, resets for the next request and clears on failure', async ({
  page,
}) => {
  let fail!: () => void;
  let pending = new Promise<void>((resolve) => {
    fail = resolve;
  });
  await page.route('**/api/connection/test', async (route) => {
    await pending;
    await route.fulfill({ status: 503, json: { error: 'Fixture connection unavailable.' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Upload project requirements' }).click();
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await expect(
    page.getByText('Stored on this computer only; excluded from workflows and exports.'),
  ).toHaveCount(0);
  await expect(page.getByText('Tests send a short request to your selected model.')).toHaveCount(0);
  await page.clock.install({ time: new Date('2026-11-07T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-07T12:00:01Z'));
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await page.clock.fastForward(8000);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss progress update' }).click();
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Test connection', exact: true })).toBeDisabled();
  fail();
  await expect(page.getByRole('alert')).toContainText('Fixture connection unavailable.');
  pending = new Promise<void>((resolve) => {
    fail = resolve;
  });
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await page.clock.fastForward(8000);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toBeVisible();
  fail();
  await expect(page.getByRole('alert')).toContainText('Fixture connection unavailable.');
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toHaveCount(0);
});

test('returning home through the logo clears the document analysis notice', async ({ page }) => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route('**/api/requirements/extract', (route) =>
    route.fulfill({
      json: {
        document: { filename: 'brief.txt', text: 'Prepare a report.', page_count: 1, warnings: [] },
      },
    }),
  );
  await page.route('**/api/requirements/analyze', async (route) => {
    await pending;
    await route.fulfill({ status: 503, json: { error: 'Fixture analysis unavailable.' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Upload project requirements' }).click();
  await page.getByTestId('requirements-file-input').setInputFiles({
    name: 'brief.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Prepare a report.'),
  });
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    'Prepare a report.',
  );
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.clock.install({ time: new Date('2026-11-07T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-07T12:00:01Z'));
  await page.getByRole('button', { name: 'Analyze requirements', exact: true }).click();
  await page.clock.fastForward(8000);
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'KNOT home', exact: true }).click();
  await expect(page.getByTestId('home-page')).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: 'Progress update', exact: true }),
  ).toHaveCount(0);
  finish();
});

test('every page exposes one home logo and returning home preserves project edits', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect(page.locator('.block-card')).toHaveCount(example.nodes.length);
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill('Keep this agent edit');
  await page.getByRole('link', { name: 'KNOT home', exact: true }).click();
  await expect(page.getByTestId('home-page')).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => JSON.parse(localStorage.getItem('knot.current.v1') || 'null')?.agents[0]?.name,
      ),
    )
    .toBe('Keep this agent edit');
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!));
  for (const route of [
    '/workspace',
    '/new',
    '/workspace/agents',
    '/workspace/project',
    '/workspace/designer',
    '/workspace/check',
    '/projects',
    '/guide',
    '/workspace/export',
  ]) {
    await page.goto('/#' + route);
    const home = page.getByRole('link', { name: 'KNOT home', exact: true });
    await expect(home).toHaveCount(1);
    await expect(home).toBeVisible();
    await expect(page.getByRole('button', { name: 'Home', exact: true })).toHaveCount(0);
    await home.click();
    await expect(page.getByTestId('home-page')).toBeVisible();
  }
  const current = await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!));
  expect(current.project).toEqual(saved.project);
  expect(current.agents).toEqual(saved.agents);
  expect(current.nodes).toEqual(saved.nodes);
  expect(current.edges).toEqual(saved.edges);
});
