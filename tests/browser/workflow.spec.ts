import { test, expect, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

// The introduction has its own first-visit suite; these tests exercise the editor.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
});

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
  await expect(page.getByText('Ready to export your workspace.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export runner' }).click();
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  const bundle = await downloadEvent;
  await bundle.saveAs(resolve(artifactDir, 'manual-runner.zip'));
  await expect(page.getByText('Your agents have their assignments.')).toBeVisible();
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

for (const prefix of ['knot', 'teamblocks']) {
  test(`new home opens ${prefix} saved projects and preserves the separate planner connection`, async ({
    page,
  }) => {
    const current = JSON.parse(readFileSync(resolve('examples/team-research.json'), 'utf8'));
    current.project.name = 'Saved current project';
    current.agents[0].model = 'saved-execution-model';
    const library = structuredClone(current);
    library.project.id = 'saved-library-project';
    library.project.name = 'Saved library project';
    library.nodes.find((node: any) => node.id === 'research').label = 'Preserved library task';
    const planner = {
      provider: 'openai',
      model: 'saved-planning-model',
      credential_ref: 'SAVED_PLANNER_API_KEY',
      base_url: 'https://saved-planner.example.invalid/v1',
    };
    await page.addInitScript(
      ({ prefix, current, library, planner }) => {
        if (sessionStorage.getItem('fixture-projects-seeded')) return;
        localStorage.setItem(`${prefix}.current.v1`, JSON.stringify(current));
        localStorage.setItem(`${prefix}.projects.v1`, JSON.stringify([library]));
        localStorage.setItem(`${prefix}.planner.v1`, JSON.stringify(planner));
        sessionStorage.setItem('fixture-projects-seeded', 'true');
      },
      { prefix, current, library, planner },
    );
    await page.goto('/');
    await expect(page).toHaveTitle(/^KNOT/);
    await expect(page.getByRole('link', { name: 'KNOT home', exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Saved current project/ }).click();
    await expect(page).toHaveURL(/#\/workspace$/);
    const restored = await getWorkflow(page);
    expect(restored.project).toEqual(current.project);
    expect(restored.agents).toEqual(current.agents);
    expect(restored.nodes).toEqual(current.nodes);
    expect(restored.edges).toEqual(current.edges);
    await page.getByRole('button', { name: 'AI designer', exact: true }).click();
    await expect(page.getByLabel('Planning model', { exact: true })).toHaveValue(planner.model);
    await expect(page.getByLabel('Credential environment variable', { exact: true })).toHaveValue(
      planner.credential_ref,
    );
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await page.getByRole('link', { name: 'KNOT home', exact: true }).click();
    await page.getByRole('button', { name: 'My projects', exact: true }).click();
    const opened = page.waitForEvent('popup');
    await page
      .getByRole('link', { name: 'Open Saved library project in a new tab', exact: true })
      .click();
    const projectTab = await opened;
    await expect(page).toHaveURL(/#\/projects$/);
    await expect(projectTab.getByText('Preserved library task', { exact: true })).toBeVisible();
    await projectTab.getByRole('button', { name: 'Save', exact: true }).click();
    await projectTab.reload();
    expect((await getWorkflow(projectTab)).nodes).toEqual(library.nodes);
    expect(
      await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!).project.id),
    ).toBe(current.project.id);
    expect(
      await page.evaluate(() => JSON.parse(localStorage.getItem('knot.planner.v1') || 'null')),
    ).toEqual(planner);
    if (prefix === 'teamblocks') {
      expect(
        await page.evaluate(() =>
          JSON.parse(localStorage.getItem('teamblocks.current.v1') || 'null'),
        ),
      ).toEqual(current);
    }
  });
}

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
    .fill('KNOT_TEST_MISSING_KEY');
  await expect(page.locator('.key-state')).toHaveText('Credential status not checked');
  await page.getByLabel('Planning model', { exact: true }).fill('user-configured-model');
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(/credential|key|configure|未配置|凭证/i);
  await expect(page.getByRole('region', { name: 'planner', exact: true })).toBeVisible();
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
  await expect(page.getByText('Ready to export your workspace.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Export runnable ZIP' }).click();
  await expect(page.getByRole('heading', { name: 'One choice. Every agent.' })).toBeVisible();
  await page.getByLabel('Run with', { exact: true }).selectOption('claude');
  await page.getByLabel('Shared model (optional)', { exact: true }).fill('test-shared-model');
  const d = page.waitForEvent('download');
  const request = page.waitForRequest((value) => value.url().endsWith('/api/export'));
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await (await d).saveAs(resolve(artifactDir, 'template-runner.zip'));
  await expect(page.getByText('Your agents have their assignments.')).toBeVisible();
  const body = (await request).postDataJSON();
  expect(body.execution).toEqual({ backend: 'claude', model: 'test-shared-model' });
  expect(body.workflow.agents.every((agent: any) => agent.model === '')).toBe(true);
  await expect(
    page.getByText('Every role will use Claude with test-shared-model.', { exact: false }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test('export instructions copy platform commands without starting work and fit small screens', async ({
  page,
}) => {
  const exports: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/api/export')) exports.push(request.url());
  });
  await page.addInitScript(() => {
    (window as any).__copiedCommands = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          (window as any).__copiedCommands.push(value);
        },
      },
    });
  });
  await openTemplate(page);
  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  const guide = page.getByRole('region', { name: 'Run on your computer' });
  await expect(guide).toBeVisible();
  await guide.getByRole('button', { name: 'Windows · PowerShell', exact: true }).click();
  await expect(guide.locator('.export-command code').first()).toHaveText(
    '.\\knot.cmd run --interactive',
  );
  await guide.getByRole('button', { name: 'Copy start command' }).click();
  await expect(guide.getByRole('status')).toContainText('Start command copied');
  await guide.getByRole('button', { name: 'Copy monitor command' }).click();
  await guide.getByRole('button', { name: 'macOS / Linux', exact: true }).click();
  await expect(guide.locator('.export-command code').first()).toHaveText(
    'sh knot.sh run --interactive',
  );
  await guide.getByRole('button', { name: 'Copy start command' }).click();
  await guide.getByRole('button', { name: 'Copy monitor command' }).click();
  expect(await page.evaluate(() => (window as any).__copiedCommands)).toEqual([
    '.\\knot.cmd run --interactive',
    '.\\knot.cmd monitor',
    'sh knot.sh run --interactive',
    'sh knot.sh monitor',
  ]);
  expect(exports).toEqual([]);
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async () => {
          throw new Error('Clipboard permission denied');
        },
      },
    });
  });
  await guide.getByRole('button', { name: 'Copy start command' }).click();
  await expect(guide.getByRole('status')).toContainText('copy it manually');
  await guide.getByRole('button', { name: 'Windows · PowerShell', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await download;
  await expect(page.getByText('Your agents have their assignments.')).toBeVisible();
  await expect(guide.locator('.export-command code').first()).toHaveText(
    '.\\knot.cmd run --interactive',
  );
  await expect(guide).toContainText('This only watches progress. It does not start another run.');
  for (const width of [1280, 768, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    await guide.getByRole('button', { name: 'Copy monitor command' }).scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(
      await guide
        .locator('code')
        .first()
        .evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
    ).toBeGreaterThanOrEqual(16);
    const bounds = await guide.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: resolve(artifactDir, `export-commands-${width}.png`),
      fullPage: true,
    });
  }
  await page.getByRole('button', { name: 'Back to canvas', exact: true }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
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
  await expect(page.locator('.key-state')).toHaveText('Saved on this device');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.locator('.connection-feedback[role=status]')).toContainText(
    'Connection verified by test fixture.',
  );
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain(fixtureKey);
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

test('a cancelled generation cannot replace another project or unlock its pending generation', async ({
  page,
}) => {
  const other = JSON.parse(readFileSync(resolve('examples/team-research.json'), 'utf8'));
  other.project.id = 'other-saved-project';
  other.project.name = 'Other saved project';
  other.nodes.find((node: any) => node.id === 'research').label = 'Other project original task';
  await page.addInitScript((other) => {
    localStorage.setItem('knot.projects.v1', JSON.stringify([other]));
  }, other);
  const requests: any[] = [];
  const releases: (() => void)[] = [];
  const arrivals: (() => void)[] = [];
  const arrived = [0, 1].map(
    (index) => new Promise<void>((resolve) => (arrivals[index] = resolve)),
  );
  const gates = [0, 1].map((index) => new Promise<void>((resolve) => (releases[index] = resolve)));
  await page.route('**/api/plan', async (route) => {
    const index = requests.length;
    const request = route.request().postDataJSON();
    requests.push(request);
    arrivals[index]();
    await gates[index];
    const workflow = structuredClone(other);
    workflow.project = request.project;
    workflow.resources = request.resources;
    workflow.nodes.find((node: any) => node.id === 'research').label =
      index === 0 ? 'Stale generated graph' : 'Fresh generated graph';
    await route.fulfill({ json: { workflow } });
  });
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await arrived[0];
  await page.goBack();
  await expect(page).toHaveURL(/#\/workspace$/);
  const importProject = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Import JSON', exact: true }).click();
  await (
    await importProject
  ).setFiles({
    name: 'other-project.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(other)),
  });
  expect((await getWorkflow(page)).project).toEqual(other.project);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByRole('button', { name: 'Generate with AI', exact: true }).click();
  await arrived[1];
  expect(requests[1].project.id).toBe(other.project.id);
  const oldResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/plan') &&
      response.request().postDataJSON().project.id === requests[0].project.id,
  );
  releases[0]();
  await (await oldResponse).finished();
  // Let the resolved fetch and React update finish while request two is still held.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(page).toHaveURL(/#\/workspace\/designer$/);
  await expect(
    page.getByRole('button', { name: 'Designing your workflow…', exact: true }),
  ).toBeDisabled();
  await expect(page.locator('.project-name h1')).toHaveText(other.project.name);
  await expect(page.getByText('Stale generated graph', { exact: true })).toHaveCount(0);
  releases[1]();
  await expect(page.getByText('Fresh generated graph', { exact: true })).toBeVisible();
  const result = await getWorkflow(page);
  expect(result.project).toEqual(other.project);
  expect(result.resources).toEqual(other.resources);
});
