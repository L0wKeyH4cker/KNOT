import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

test('member API example opens, keeps owner routing and exports a real OpenCode package without keys', async ({
  page,
}) => {
  // Use the real local template, validation and export APIs. This test neither
  // saves credentials nor starts tasks or sends a model request.
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/')) apiRequests.push(path);
  });
  await page.goto('/');
  const templateResponse = page.waitForResponse('**/api/template/owner-api');
  await page.getByRole('button', { name: 'Test member APIs', exact: true }).click();
  const response = await templateResponse;
  expect(response.status()).toBe(200);
  const sample = await response.json();
  expect(sample.project.members.map((member: any) => member.name)).toEqual([
    'Alice（用户 A）',
    'Bob（用户 B）',
  ]);
  await expect(page.getByTestId('workflow-canvas')).toBeVisible();
  await expect(page.locator('.block-card')).toHaveCount(sample.nodes.length);
  const tasks = sample.nodes.filter((node: any) => node.type === 'agent_task');
  expect(tasks).toHaveLength(3);
  const [alice, bob] = sample.project.members;
  expect(tasks.filter((node: any) => node.config.owner_id === alice.id)).toHaveLength(2);
  expect(tasks.filter((node: any) => node.config.owner_id === bob.id)).toHaveLength(1);
  for (const task of tasks) {
    await page.getByTestId(`block-${task.id}`).click();
    await expect(page.getByLabel('Human owner', { exact: true })).toHaveValue(task.config.owner_id);
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  }

  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  await expect(page.getByLabel('Run with', { exact: true })).toHaveValue('opencode');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  await expect(page).toHaveURL(/#\/workspace\/check$/);
  await expect(page.getByText(/enter a model for Alice/).first()).toBeVisible();
  await expect(page.getByText(/enter a model for Bob/).first()).toBeVisible();
  expect(apiRequests).not.toContain('/api/export');

  await page.getByRole('button', { name: 'Project settings', exact: true }).click();
  const refs: string[] = [];
  const models = ['fixture-alice-model', 'fixture-bob-model'];
  for (let index = 0; index < 2; index++) {
    const member = sample.project.members[index];
    const card = page.getByRole('article', { name: `Member ${index + 1} settings`, exact: true });
    await expect(card.getByLabel(`Member ${index + 1} name`, { exact: true })).toHaveValue(
      member.name,
    );
    await card
      .getByRole('button', { name: `Configure connection for ${member.name}`, exact: true })
      .click();
    await expect(card.getByLabel('Model name', { exact: true })).toHaveValue('');
    await card.getByLabel('Model name', { exact: true }).fill(models[index]);
    await expect(card.getByLabel('API key', { exact: true })).toHaveValue('');
    await card.getByText('Advanced connection settings', { exact: true }).click();
    refs.push(await card.getByLabel('Credential reference', { exact: true }).inputValue());
    await card.getByText('Advanced connection settings', { exact: true }).click();
  }
  expect(new Set(refs).size).toBe(2);
  expect(refs).toEqual(['KNOT_DEMO_ALICE_API_KEY', 'KNOT_DEMO_BOB_API_KEY']);
  const artifactDir = resolve('artifacts/owner-opencode');
  mkdirSync(artifactDir, { recursive: true });
  await page
    .getByRole('article', { name: 'Member 1 settings', exact: true })
    .evaluate((element) => element.scrollIntoView({ block: 'start' }));
  await page.getByRole('button', { name: 'Dismiss notification', exact: true }).click();
  await page.screenshot({ path: resolve(artifactDir, 'example-members.png'), fullPage: true });
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('button', { name: 'Fit View', exact: true }).click();
  await page.screenshot({ path: resolve(artifactDir, 'example-canvas.png'), fullPage: true });
  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  await expect(page.getByLabel('Run with', { exact: true })).toHaveValue('opencode');
  const includeKeys = page.getByRole('checkbox', {
    name: 'Include saved member API keys',
    exact: true,
  });
  // This real-server test never saves keys, so explicitly export the sharing package.
  if (await includeKeys.isEnabled()) await includeKeys.uncheck();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download agent workspace', exact: true }).click();
  const download = await downloadEvent;
  const bundlePath = resolve(artifactDir, 'example-configured-fixture.zip');
  await download.saveAs(bundlePath);

  const python =
    process.env.PYTHON ||
    spawnSync(process.execPath, ['scripts/dev.mjs', '--check-python'], {
      encoding: 'utf8',
    }).stdout.trim();
  const inspect = spawnSync(
    python,
    [
      '-c',
      `
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as bundle:
    assert '.env' not in bundle.namelist()
    workflow = json.loads(bundle.read('workflow.json'))
    execution = json.loads(bundle.read('knot.json'))
    env = bundle.read('.env.example').decode('utf-8')
    for member in workflow['project']['members']:
        ref = member['connection']['credential_ref']
        assert ref + '=' in env.splitlines(), 'Member credential must remain empty'
    print(json.dumps({'workflow': workflow, 'execution': execution}))
`,
      bundlePath,
    ],
    { encoding: 'utf8', timeout: 15000 },
  );
  expect(inspect.status, inspect.stderr).toBe(0);
  const exported = JSON.parse(inspect.stdout);
  expect(exported.execution.backend).toBe('opencode');
  expect(exported.execution.model).toBe('');
  expect(exported.workflow.project.members.map((member: any) => member.connection.model)).toEqual(
    models,
  );
  expect(
    exported.workflow.project.members.map((member: any) => member.connection.credential_ref),
  ).toEqual(refs);
  expect(
    exported.workflow.nodes
      .filter((node: any) => node.type === 'agent_task')
      .map((node: any) => node.config.owner_id),
  ).toEqual(tasks.map((node: any) => node.config.owner_id));
  expect(apiRequests).not.toContain('/api/credentials');
  expect(apiRequests).not.toContain('/api/connection/test');
  expect(apiRequests).not.toContain('/api/plan');
});
