import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Configuration tests only: custom endpoints are deliberately non-routable and
// model-generating routes are blocked so this suite cannot spend API tokens.
const modelCalls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => {
  const calls: string[] = [];
  modelCalls.set(page, calls);
  await page.route(/\/api\/(?:plan|requirements\/analyze)$/, async (route) => {
    calls.push(route.request().url());
    await route.abort();
  });
});
test.afterEach(async ({ page }) => {
  expect(modelCalls.get(page)).toEqual([]);
});

async function openTemplate(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
}

async function getWorkflow(page: Page) {
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  const file = await download;
  return JSON.parse(readFileSync((await file.path())!, 'utf8'));
}

async function chooseAgent(page: Page, name: string) {
  await page.locator('.agent-choice').filter({ hasText: name }).click();
}

async function openAdvanced(page: Page) {
  if (
    !(await page
      .locator('.connection-advanced')
      .evaluate((element) => (element as HTMLDetailsElement).open))
  )
    await page.getByText('Advanced connection settings', { exact: true }).click();
}

const configurations = [
  {
    id: 'researcher',
    name: 'Research partner',
    provider: 'openai',
    model: 'fixture-research-model',
    credential_ref: 'RESEARCH_API_KEY',
    base_url: 'https://research.example.invalid/v1',
  },
  {
    id: 'analyst',
    name: 'Data partner',
    provider: 'anthropic',
    model: 'fixture-analysis-model',
    credential_ref: 'ANALYSIS_API_KEY',
    base_url: 'https://analysis.example.invalid/v1',
  },
  {
    id: 'editor',
    name: 'Story partner',
    provider: 'openai',
    model: 'fixture-editor-model',
    credential_ref: 'EDITOR_API_KEY',
    base_url: 'https://editor.example.invalid/v1',
  },
];

test('three agents retain independent API settings and task assignments after save, reload and JSON export', async ({
  page,
}) => {
  await openTemplate(page);
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  for (const agent of configurations) {
    await chooseAgent(page, agent.name);
    await page.getByLabel('Provider', { exact: true }).selectOption(agent.provider);
    await page.getByLabel('Model name', { exact: true }).fill(agent.model);
    await openAdvanced(page);
    await page.getByLabel('Credential reference', { exact: true }).fill(agent.credential_ref);
    await page.getByLabel('API base URL (optional)', { exact: true }).fill(agent.base_url);
  }
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  // Explicitly bind each task through the editor, rather than only relying on
  // the template's existing bindings.
  for (const [task, agent] of [
    ['research', 'analyst'],
    ['analysis', 'researcher'],
    ['synthesis', 'editor'],
  ]) {
    await page.getByTestId(`block-${task}`).click();
    await page.getByLabel('Agent', { exact: true }).selectOption(agent);
    await page.getByRole('button', { name: 'Close settings' }).click();
  }
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.reload();
  await expect(page.locator('.block-card')).toHaveCount(8);
  const workflow = await getWorkflow(page);
  for (const config of configurations) {
    expect(workflow.agents.find((agent: any) => agent.id === config.id)).toMatchObject(config);
  }
  expect(workflow.nodes.find((node: any) => node.id === 'research').config.agent_id).toBe(
    'analyst',
  );
  expect(workflow.nodes.find((node: any) => node.id === 'analysis').config.agent_id).toBe(
    'researcher',
  );
  expect(workflow.nodes.find((node: any) => node.id === 'synthesis').config.agent_id).toBe(
    'editor',
  );

  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  for (const agent of configurations) {
    await chooseAgent(page, agent.name);
    await expect(page.getByLabel('Provider', { exact: true })).toHaveValue(
      agent.provider === 'openai' ? 'custom' : 'anthropic',
    );
    await openAdvanced(page);
    await expect(page.getByLabel('Model name', { exact: true })).toHaveValue(agent.model);
    await expect(page.getByLabel('Credential reference', { exact: true })).toHaveValue(
      agent.credential_ref,
    );
    await expect(page.getByLabel('API base URL (optional)', { exact: true })).toHaveValue(
      agent.base_url,
    );
  }
});

test('switching provider clears incompatible model and address for an agent and the independent planner', async ({
  page,
}) => {
  await openTemplate(page);
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await page.getByLabel('Model name', { exact: true }).fill('old-provider-model');
  await openAdvanced(page);
  await page.getByLabel('Credential reference', { exact: true }).fill('OLD_PROVIDER_API_KEY');
  await page
    .getByLabel('API base URL (optional)', { exact: true })
    .fill('https://old.example.invalid/v1');
  await page.getByLabel('Provider', { exact: true }).selectOption('anthropic');
  await openAdvanced(page);
  await expect(page.getByLabel('Model name', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Credential reference', { exact: true })).toHaveValue(
    'ANTHROPIC_API_KEY',
  );
  await expect(page.getByLabel('API base URL (optional)', { exact: true })).toHaveValue('');
  await page.getByLabel('Model name', { exact: true }).fill('execution-model');
  await page.getByLabel('Credential reference', { exact: true }).fill('EXECUTION_API_KEY');
  await page
    .getByLabel('API base URL (optional)', { exact: true })
    .fill('https://execution.example.invalid/v1');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  const beforePlanner = await getWorkflow(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByLabel('Planning model', { exact: true }).fill('old-planning-model');
  await openAdvanced(page);
  await page
    .getByLabel('Credential environment variable', { exact: true })
    .fill('PLANNING_API_KEY');
  await page
    .getByLabel('API base URL (optional)', { exact: true })
    .fill('https://planning.example.invalid/v1');
  await page.getByLabel('Planning provider', { exact: true }).selectOption('anthropic');
  await openAdvanced(page);
  await expect(page.getByLabel('Planning model', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Credential environment variable', { exact: true })).toHaveValue(
    'ANTHROPIC_API_KEY',
  );
  await expect(page.getByLabel('API base URL (optional)', { exact: true })).toHaveValue('');
  await page.getByLabel('Planning model', { exact: true }).fill('independent-planner-model');
  await page.reload();
  await expect(page.getByLabel('Planning model', { exact: true })).toHaveValue(
    'independent-planner-model',
  );
  await expect(page.getByLabel('Planning provider', { exact: true })).toHaveValue('anthropic');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  expect((await getWorkflow(page)).agents).toEqual(beforePlanner.agents);
});

test('a custom credential reference is shown as unchecked instead of incorrectly missing', async ({
  page,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        planner_credentials: { OPENAI_API_KEY: true, ANTHROPIC_API_KEY: false },
      }),
    }),
  );
  await page.route('**/api/connection/test', async (route) => {
    expect(route.request().postDataJSON().connection.credential_ref).toBe('CUSTOM_ROUTER_API_KEY');
    await route.fulfill({ json: { ok: true, message: 'Custom reference checked by fixture.' } });
  });
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  const status = page.locator('.key-state');
  await expect(status).toHaveText('Saved on this device');
  await openAdvanced(page);
  await page
    .getByLabel('Credential environment variable', { exact: true })
    .fill('CUSTOM_ROUTER_API_KEY');
  await expect(status).toHaveText('Credential status not checked');
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-model');
  await expect(page.getByRole('button', { name: 'Generate with AI', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.locator('.connection-feedback[role=status]')).toContainText(
    'Custom reference checked by fixture.',
  );
  await page
    .getByLabel('Credential environment variable', { exact: true })
    .fill('ANTHROPIC_API_KEY');
  await expect(status).toHaveText('Not configured');
  await expect(page.getByRole('button', { name: 'Test connection', exact: true })).toBeDisabled();
  await page.getByLabel('Credential environment variable', { exact: true }).fill('OPENAI_API_KEY');
  await expect(status).toHaveText('Saved on this device');
});
