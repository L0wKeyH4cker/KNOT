import { test, expect, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const artifactDir = resolve('artifacts/browser');
mkdirSync(artifactDir, { recursive: true });
async function openTemplate(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
}
async function getWorkflow(page: Page) {
  const event = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  const file = await event;
  const path = await file.path();
  return JSON.parse(readFileSync(path!, 'utf8'));
}
async function closeInspector(page: Page) {
  const close = page.getByRole('button', { name: 'Close settings' });
  if (await close.isVisible()) await close.click();
}
async function connect(
  page: Page,
  source: string,
  target: string,
  sourcePort = 'out',
  targetPort = 'in',
) {
  const a = page.locator(`[data-testid="block-${source}"] [data-handleid="${sourcePort}"]`),
    b = page.locator(`[data-testid="block-${target}"] [data-handleid="${targetPort}"]`);
  await a.hover();
  await b.hover();
  await a.hover();
  const ab = await a.boundingBox(),
    bb = await b.boundingBox();
  expect(ab).not.toBeNull();
  expect(bb).not.toBeNull();
  await page.mouse.move(ab!.x + ab!.width / 2, ab!.y + ab!.height / 2);
  await page.mouse.down();
  await page.mouse.move(bb!.x + bb!.width / 2, bb!.y + bb!.height / 2, { steps: 16 });
  await page.mouse.up();
}

test('create from scratch, drag blocks, connect ports, configure agent and export an executable manual workflow', async ({
  page,
}) => {
  await page.goto('/');
  await page.screenshot({ path: resolve(artifactDir, 'onboarding.png'), fullPage: true });
  await expect(page.getByTestId('home-page')).toBeVisible();
  await expect(page.getByTestId('workflow-canvas')).toHaveCount(0);
  await page
    .getByLabel('Describe your project')
    .fill('Write a concise report from the assigned task.');
  await page.getByRole('button', { name: 'Continue to project setup' }).click();
  await expect(page).toHaveURL(/#\/new$/);
  await expect(page.getByLabel('What are you working on?')).toHaveValue(
    'Write a concise report from the assigned task.',
  );
  await page.getByLabel('Project name', { exact: true }).fill('Manual canvas test');
  await page.getByLabel('Team size', { exact: true }).fill('3');
  await page.getByLabel('Final deliverable', { exact: true }).fill('A Markdown report');
  await page
    .getByLabel('What are you working on?')
    .fill('Write a concise report from the assigned task.');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('button', { name: /Start from scratch/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Generate with AI/ })).toBeVisible();
  await page.getByRole('button', { name: /Start from scratch/ }).click();
  for (const [kind, x] of [
    ['start', 100],
    ['agent_task', 420],
    ['output', 760],
  ] as const) {
    await page
      .getByTestId(`palette-${kind}`)
      .dragTo(page.locator('.react-flow__pane'), { targetPosition: { x, y: 200 } });
    await closeInspector(page);
  }
  await expect(page.locator('.block-card')).toHaveCount(3);
  const before = await getWorkflow(page);
  const start = before.nodes.find((n: any) => n.type === 'start'),
    task = before.nodes.find((n: any) => n.type === 'agent_task'),
    out = before.nodes.find((n: any) => n.type === 'output');
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill('Writer');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByTestId(`block-${task.id}`).click();
  await page.getByLabel('Agent', { exact: true }).selectOption({ label: 'Writer' });
  await page.getByLabel('Task instructions').fill('Write a report about our demo workflow.');
  await page.getByLabel('Acceptance criteria').fill('Clear Markdown content.');
  await closeInspector(page);
  await connect(page, start.id, task.id);
  await connect(page, task.id, out.id);
  await connect(page, task.id, out.id, 'data-out', 'data-in');
  await expect(page.locator('.react-flow__edge')).toHaveCount(3);
  await page.getByTestId(`block-${out.id}`).click();
  await page.getByRole('button', { name: 'Add delivery file' }).click();
  await closeInspector(page);
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await expect(page.getByText('Ready for a mock run.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export runner' }).click();
  const bundle = await downloadEvent;
  await bundle.saveAs(resolve(artifactDir, 'manual-runner.zip'));
  await expect(page.getByText('Take your team’s workflow with you.')).toBeVisible();
  const python =
    process.env.PYTHON ||
    spawnSync(process.execPath, ['scripts/dev.mjs', '--check-python'], {
      encoding: 'utf8',
    }).stdout.trim();
  const run = spawnSync(
    python,
    [
      '-c',
      `import tempfile,zipfile,subprocess,sys,pathlib; t=tempfile.TemporaryDirectory(); p=pathlib.Path(t.name); zipfile.ZipFile(sys.argv[1]).extractall(p); r=subprocess.run([sys.executable,'run.py','--mode','mock'],cwd=p,capture_output=True,text=True); print(r.stdout); print(r.stderr); assert r.returncode==0; assert (p/'results'/'report.md').exists()`,
      resolve(artifactDir, 'manual-runner.zip'),
    ],
    { encoding: 'utf8', timeout: 30000 },
  );
  expect(run.status, run.stdout + run.stderr).toBe(0);
});

test('example blocks move freely, connections follow, undo/redo, duplicate/delete and reload preserve graph', async ({
  page,
}) => {
  await openTemplate(page);
  await page.getByRole('button', { name: 'Fit View', exact: true }).click();
  const initial = await getWorkflow(page);
  const task = initial.nodes.find((n: any) => n.type === 'agent_task');
  const card = page.getByTestId(`block-${task.id}`),
    box = await card.boundingBox();
  await page.mouse.move(box!.x + 65, box!.y + 30);
  await page.mouse.down();
  await page.mouse.move(box!.x + 150, box!.y + 90, { steps: 14 });
  await page.mouse.up();
  await closeInspector(page);
  const moved = await getWorkflow(page);
  expect(moved.nodes.find((n: any) => n.id === task.id).position).not.toEqual(task.position);
  expect(moved.edges).toEqual(initial.edges);
  await page.getByRole('button', { name: 'Undo (Ctrl+Z)' }).click();
  const undone = await getWorkflow(page);
  expect(undone.nodes.find((n: any) => n.id === task.id).position).toEqual(task.position);
  await page.getByRole('button', { name: 'Redo (Ctrl+Shift+Z)' }).click();
  await page.getByTestId(`block-${task.id}`).click();
  await page.getByLabel('Block name').fill('Edited research task');
  await page.getByRole('button', { name: 'Duplicate', exact: true }).click();
  await expect(page.locator('.block-card')).toHaveCount(9);
  await page.getByRole('button', { name: 'Delete block', exact: true }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.reload();
  await expect(page.getByText('Edited research task', { exact: true })).toBeVisible();
  const restored = await getWorkflow(page);
  expect(restored.edges).toEqual(initial.edges);
  expect(restored.nodes.find((n: any) => n.id === task.id).position).toEqual(
    moved.nodes.find((n: any) => n.id === task.id).position,
  );
  await page.screenshot({ path: resolve(artifactDir, 'canvas-desktop.png'), fullPage: true });
});

test('real port dragging rejects cycles, deletes and reconnects edges, and checks missing inputs', async ({
  page,
}) => {
  await openTemplate(page);
  const w = await getWorkflow(page);
  const task = w.nodes.find((n: any) => n.type === 'agent_task');
  const synthesis =
    w.nodes.find((n: any) => n.id === 'synthesis') ||
    w.nodes.filter((n: any) => n.type === 'agent_task')[2];
  await connect(page, synthesis.id, task.id);
  await expect(page.getByRole('status')).toContainText('cycle');
  const same = await getWorkflow(page);
  expect(same.edges).toEqual(w.edges);
  const data = w.edges.find((e: any) => e.kind === 'data' && e.target === task.id);
  const selector = `[data-testid="rf__edge-${data.id}"] .react-flow__edge-interaction`;
  await page.locator(selector).click({ force: true });
  await page.getByRole('button', { name: 'Delete connection' }).click();
  expect((await getWorkflow(page)).edges).toHaveLength(w.edges.length - 1);
  await connect(page, data.source, data.target, 'data-out', 'data-in');
  expect((await getWorkflow(page)).edges).toHaveLength(w.edges.length);
  await page.getByTestId('palette-agent_task').click();
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await expect(page.getByText('A few things need your attention.')).toBeVisible();
  await expect(page.locator('.issue.error').first()).toBeVisible();
});

test('JSON round-trip preserves configuration; cyclic import is rejected without changing the canvas', async ({
  page,
}) => {
  await openTemplate(page);
  const before = await getWorkflow(page);
  const imported = {
    ...before,
    project: { ...before.project, name: 'Imported round-trip' },
    viewport: { x: 20, y: 30, zoom: 0.7 },
  };
  await page.locator('input[type=file]').setInputFiles({
    name: 'workflow.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(imported)),
  });
  await expect(
    page.getByRole('heading', { name: 'Imported round-trip', exact: true }),
  ).toBeVisible();
  const after = await getWorkflow(page);
  expect(after.nodes).toEqual(imported.nodes);
  expect(after.agents).toEqual(imported.agents);
  expect(after.resources).toEqual(imported.resources);
  expect(after.edges).toEqual(imported.edges);
  const cycle = structuredClone(imported);
  const task = cycle.nodes.find((n: any) => n.type === 'agent_task'),
    start = cycle.nodes.find((n: any) => n.type === 'start');
  cycle.edges.push({
    id: 'bad_cycle',
    source: task.id,
    target: start.id,
    source_port: 'out',
    target_port: 'in',
    kind: 'control',
  });
  await page.locator('input[type=file]').setInputFiles({
    name: 'bad.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(cycle)),
  });
  await expect(page.getByRole('status')).toContainText('Import rejected');
  expect((await getWorkflow(page)).edges).toEqual(imported.edges);
});

test('AI is honest when credentials are absent; task model and planner are separate', async ({
  page,
}) => {
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByText('Advanced connection settings', { exact: true }).click();
  await page
    .getByLabel('Credential environment variable', { exact: true })
    .fill('TEAMBLOCKS_TEST_MISSING_KEY');
  await expect(page.getByText('Not configured', { exact: true })).toBeVisible();
  await page.getByLabel('Planning model', { exact: true }).fill('user-configured-model');
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(/credential|key|configure|未配置|凭证/i);
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  expect((await getWorkflow(page)).agents.every((a: any) => a.model === '')).toBe(true);
});

test('template exports from browser and keeps review before delivery; no browser errors', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await openTemplate(page);
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await expect(page.getByText('Ready for a mock run.', { exact: true })).toBeVisible();
  const d = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export runnable ZIP' }).click();
  await (await d).saveAs(resolve(artifactDir, 'template-runner.zip'));
  await expect(page.getByText('Take your team’s workflow with you.')).toBeVisible();
  expect(errors).toEqual([]);
});

test('DeepSeek setup saves credentials separately and tests the selected compatible connection (API fixtures)', async ({
  page,
}) => {
  const fixtureKey = 'browser-connection-fixture-only';
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: { DEEPSEEK_API_KEY: false } } }),
  );
  await page.route('**/api/credentials', async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      credential_ref: 'DEEPSEEK_API_KEY',
      key: fixtureKey,
    });
    await route.fulfill({ json: { credentials: { DEEPSEEK_API_KEY: true } } });
  });
  await page.route('**/api/connection/test', async (route) => {
    expect(route.request().postDataJSON().connection).toEqual({
      provider: 'openai',
      model: 'deepseek-flash',
      credential_ref: 'DEEPSEEK_API_KEY',
      base_url: 'https://api.deepseek.com',
    });
    await route.fulfill({ json: { ok: true, message: 'Connection verified by test fixture.' } });
  });
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByLabel('Planning provider', { exact: true }).selectOption('deepseek');
  await expect(page.getByLabel('Planning model', { exact: true })).toHaveValue('deepseek-flash');
  await page.getByLabel('API key', { exact: true }).fill(fixtureKey);
  await page.getByRole('button', { name: 'Save on this device', exact: true }).click();
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('');
  await expect(page.getByText('Saved on this device', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Connection verified by test fixture.');
  await page.reload();
  await expect(page.getByLabel('Planning provider', { exact: true })).toHaveValue('deepseek');
  await expect(page.getByLabel('Planning model', { exact: true })).toHaveValue('deepseek-flash');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  expect(JSON.stringify(await getWorkflow(page))).not.toContain(fixtureKey);
});

test('small screen keeps controls usable without document overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openTemplate(page);
  await expect(page.getByRole('button', { name: 'Export runner' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: resolve(artifactDir, 'canvas-mobile.png'), fullPage: true });
});

test('edge endpoint reconnection changes data access without moving blocks', async ({ page }) => {
  await openTemplate(page);
  const w = await getWorkflow(page);
  const edge = w.edges.find(
    (e: any) => e.source === 'resources' && e.target === 'research' && e.kind === 'data',
  );
  const group = page.locator(`[data-testid="rf__edge-${edge.id}"]`);
  await group.locator('.react-flow__edge-interaction').click({ force: true });
  const handle = group.locator('.react-flow__edgeupdater-target'),
    target = page.locator('[data-testid="block-synthesis"] [data-handleid="data-in"]');
  await handle.hover();
  await target.hover();
  await handle.hover();
  const a = await handle.boundingBox(),
    b = await target.boundingBox();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, { steps: 16 });
  await page.mouse.up();
  const changed = await getWorkflow(page);
  expect(
    changed.edges.some(
      (e: any) => e.source === 'resources' && e.target === 'synthesis' && e.kind === 'data',
    ),
  ).toBe(true);
  expect(
    changed.edges.some(
      (e: any) => e.source === 'resources' && e.target === 'research' && e.kind === 'data',
    ),
  ).toBe(false);
  expect(changed.nodes).toEqual(w.nodes);
});

test('zoom, pan and saved viewport survive refresh', async ({ page }) => {
  await openTemplate(page);
  await page.getByRole('button', { name: 'Zoom In', exact: true }).click();
  await page.getByRole('button', { name: 'Zoom In', exact: true }).click();
  const pane = await page.locator('.react-flow__pane').boundingBox();
  await page.mouse.move(pane!.x + 80, pane!.y + 80);
  await page.mouse.down();
  await page.mouse.move(pane!.x + 150, pane!.y + 130, { steps: 15 });
  await page.mouse.up();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const original = await getWorkflow(page);
  await page.reload();
  await expect(page.locator('.block-card')).toHaveCount(8);
  const restored = await getWorkflow(page);
  expect(restored.viewport.zoom).toBeCloseTo(original.viewport.zoom, 4);
  expect(restored.viewport.x).toBeCloseTo(original.viewport.x, 2);
  expect(restored.viewport.y).toBeCloseTo(original.viewport.y, 2);
});

test('a schema-valid planning response remains fully editable and undoable (API fixture)', async ({
  page,
}) => {
  const response = JSON.parse(readFileSync(resolve('examples/team-research.json'), 'utf8'));
  response.nodes.find((n: any) => n.id === 'research').label = 'Generated research draft';
  await page.route('**/api/plan', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ workflow: response }),
    }),
  );
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await expect(page.getByText('Generated research draft', { exact: true })).toBeVisible();
  await page.getByTestId('block-research').click();
  await page.getByLabel('Block name', { exact: true }).fill('Human edited draft');
  await closeInspector(page);
  expect((await getWorkflow(page)).nodes.find((n: any) => n.id === 'research').label).toBe(
    'Human edited draft',
  );
  await page.getByRole('button', { name: 'Undo (Ctrl+Z)' }).click();
  await expect(page.getByText('Generated research draft', { exact: true })).toBeVisible();
});
