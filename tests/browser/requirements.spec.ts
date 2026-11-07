import { test, expect, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
});

// PDF extraction, validation and ZIP export use the real local backend. Only the
// two model responses are fixtures; this suite never calls a paid model API.
const artifactDir = resolve('artifacts/browser');
mkdirSync(artifactDir, { recursive: true });
const python =
  process.env.PYTHON ||
  spawnSync(process.execPath, ['scripts/dev.mjs', '--check-python'], {
    encoding: 'utf8',
    windowsHide: true,
  }).stdout.trim();
const requirementText = 'Compare two campus transport options using supplied data.';
const reviewedTitle = 'Compare transport options and explain the evidence';
const analysisFixture = {
  project_name: 'Campus transport study',
  goal: requirementText,
  deliverables: ['report.md with a recommendation', 'summary.csv with comparison data'],
  tasks: [
    {
      title: 'Compare transport options',
      description: 'Read the supplied transport data and compare two options.',
      acceptance: 'State the source and limitations for both options.',
      source_pages: [1],
    },
    {
      title: 'Prepare the report and comparison table',
      description: 'Use the comparison to prepare report.md and summary.csv.',
      acceptance: 'Both files explain the recommendation and the data limitations.',
      source_pages: [2],
    },
  ],
  constraints: ['Use supplied data only.'],
  missing_information: ['The transport dataset has not been supplied.'],
};

let textPdf: Buffer;
let scannedPdf: Buffer;
test.beforeAll(() => {
  const fixture = spawnSync(
    python,
    [
      '-c',
      `import base64,json,sys,backend
sys.path.insert(0,'tests')
from test_documents import make_text_pdf
pages = [${JSON.stringify(requirementText + '\nUse supplied data only.')}, 'Deliver report.md and summary.csv. State limitations.']
print(json.dumps({'text':base64.b64encode(make_text_pdf(pages)).decode(), 'scanned':base64.b64encode(make_text_pdf([None])).decode()}))`,
    ],
    { encoding: 'utf8', timeout: 30000, windowsHide: true },
  );
  expect(fixture.status, fixture.stderr).toBe(0);
  const files = JSON.parse(fixture.stdout);
  textPdf = Buffer.from(files.text, 'base64');
  scannedPdf = Buffer.from(files.scanned, 'base64');
});

async function getWorkflow(page: Page) {
  const event = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  const file = await event;
  return JSON.parse(readFileSync((await file.path())!, 'utf8'));
}

async function openTemplate(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
}

async function uploadPdf(page: Page, buffer = textPdf, name = 'project-requirements.pdf') {
  await page.getByTestId('requirements-file-input').setInputFiles({
    name,
    mimeType: 'application/pdf',
    buffer,
  });
}

async function analyze(page: Page) {
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.getByRole('button', { name: 'Analyze requirements', exact: true }).click();
  await expect(page.getByLabel('Task 1 title', { exact: true })).toHaveValue(
    analysisFixture.tasks[0].title,
  );
}

async function modelFixtures(page: Page) {
  const analysisRequests: any[] = [];
  const planRequests: any[] = [];
  await page.route('**/api/requirements/analyze', async (route) => {
    analysisRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ analysis: analysisFixture }),
    });
  });
  await page.route('**/api/plan', async (route) => {
    const request = route.request().postDataJSON();
    planRequests.push(request);
    const workflow = JSON.parse(readFileSync(resolve('examples/team-research.json'), 'utf8'));
    const originalMembers = workflow.project.members;
    for (const node of workflow.nodes) {
      const owner = originalMembers.findIndex((member: any) => member.id === node.config.owner_id);
      if (owner >= 0) node.config.owner_id = request.project.members[owner].id;
    }
    workflow.project = request.project;
    workflow.resources = request.resources;
    workflow.nodes.find((node: any) => node.id === 'resources').config.resource_ids =
      request.resources.map((resource: any) => resource.id);
    workflow.nodes.find((node: any) => node.id === 'research').label =
      'Requirement-based comparison';
    workflow.nodes.find((node: any) => node.id === 'research').config.instructions =
      request.project.goal;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ workflow }),
    });
  });
  return { analysisRequests, planRequests };
}

test('upload actual PDF from onboarding, review tasks and preserve requirements in JSON and ZIP (model fixtures)', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Continue to project setup' }).click();
  await page.getByLabel('Project name', { exact: true }).fill('Document-led project');
  await page.getByLabel('Team size', { exact: true }).fill('3');
  // No manually entered goal or deliverable is needed for this entry point.
  await page.getByRole('button', { name: /^Upload project requirements/ }).click();
  await page.screenshot({
    path: resolve(artifactDir, 'requirements-upload.png'),
    fullPage: true,
    animations: 'disabled',
  });
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await analyze(page);
  expect(requests.analysisRequests).toHaveLength(1);
  expect(requests.analysisRequests[0].document.text).toContain(requirementText);
  expect(requests.analysisRequests[0].document.page_count).toBe(2);
  await page.getByLabel('Task 1 title', { exact: true }).fill(reviewedTitle);
  await page.getByLabel('Task 1 acceptance criteria', { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: resolve(artifactDir, 'requirements-review.png'),
    fullPage: true,
    animations: 'disabled',
  });
  await page
    .getByRole('button', { name: 'Generate workflow from requirements', exact: true })
    .click();
  await expect(page.locator('.block-card')).toHaveCount(8);
  expect(requests.planRequests).toHaveLength(1);
  const planned = requests.planRequests[0];
  expect(planned.project.goal).toContain(reviewedTitle);
  expect(planned.project.name).toBe('Document-led project');
  expect(planned.project.members).toHaveLength(3);
  expect(
    planned.resources.some((resource: any) => resource.content?.includes(requirementText)),
  ).toBe(true);

  await page.getByTestId('block-research').click();
  await page.getByLabel('Block name').fill('Human-reviewed comparison');
  await page.getByRole('button', { name: 'Close settings' }).click();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.reload();
  await expect(page.getByText('Human-reviewed comparison', { exact: true })).toBeVisible();
  const saved = await getWorkflow(page);
  const source = saved.resources.find((resource: any) =>
    resource.id.startsWith('requirements-source-'),
  );
  const analysis = saved.resources.find((resource: any) =>
    resource.id.startsWith('requirements-analysis-'),
  );
  expect(source.content).toContain(requirementText);
  expect(source.example).toBe(false);
  expect(JSON.parse(analysis.content).tasks[0].title).toBe(reviewedTitle);

  const event = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export runner', exact: true }).click();
  const bundle = await event;
  const zipPath = resolve(artifactDir, 'requirements-runner.zip');
  await bundle.saveAs(zipPath);
  const inspected = spawnSync(
    python,
    [
      '-c',
      `import json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    workflow=json.loads(archive.read('workflow.json'))
    resources=[r for r in workflow['resources'] if r['id'].startswith('requirements-')]
    assert len(resources)==2
    for resource in resources:
        assert archive.read(resource['path']).decode('utf-8')==resource['content']
    assert not any(name.lower().endswith('.pdf') for name in archive.namelist())
    print(json.dumps(workflow))`,
      zipPath,
    ],
    { encoding: 'utf8', timeout: 30000, windowsHide: true },
  );
  expect(inspected.status, inspected.stderr).toBe(0);
  expect(JSON.parse(inspected.stdout)).toEqual(saved);
});

test('a PDF with no text is rejected by the actual extraction backend without calling a model', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  const responseEvent = page.waitForResponse('**/api/requirements/extract');
  await uploadPdf(page, scannedPdf, 'scanned-requirements.pdf');
  const response = await responseEvent;
  expect(response.ok()).toBe(false);
  const failure = await response.json();
  expect(failure.error).toMatch(/OCR|文字|text|扫描/i);
  await expect(page.getByText(failure.error, { exact: true }).first()).toBeVisible();
  expect(requests.analysisRequests).toHaveLength(0);
  expect(requests.planRequests).toHaveLength(0);
});

test('closing after extraction leaves the existing workflow and resources unchanged', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await openTemplate(page);
  const original = await getWorkflow(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  const cancelled = await getWorkflow(page);
  // Initial template fitting can still animate the viewport after the first
  // export. Compare every project/graph field, including node positions.
  expect({ ...cancelled, viewport: original.viewport }).toEqual(original);
  expect(requests.analysisRequests).toHaveLength(0);
  expect(requests.planRequests).toHaveLength(0);
});

test('browser Back cancels a new requirements draft before editing an existing project', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await openTemplate(page);
  const original = await getWorkflow(page);
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await page.getByRole('button', { name: 'Upload project requirements', exact: true }).click();
  await expect(page.getByTestId('requirements-file-input')).toBeAttached();
  await page.goBack();
  await expect(page.getByTestId('home-page')).toBeVisible();
  await page.locator('.recent-project').filter({ hasText: original.project.name }).click();
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await analyze(page);
  await page
    .getByRole('button', { name: 'Generate workflow from requirements', exact: true })
    .click();
  await expect(page.getByText('Requirement-based comparison', { exact: true })).toBeVisible();
  expect(requests.planRequests).toHaveLength(1);
  const generated = await getWorkflow(page);
  for (const result of [requests.planRequests[0], generated]) {
    expect(result.project.id).toBe(original.project.id);
    expect(result.project.name).toBe(original.project.name);
    expect(result.project.members).toEqual(original.project.members);
    expect(result.resources).toEqual(expect.arrayContaining(original.resources));
    expect(
      result.resources.filter((resource: any) => resource.id.startsWith('requirements-')),
    ).toHaveLength(2);
  }
});

test('home Add requirements creates a new project directly from the reviewed document', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Upload project requirements', exact: true }).click();
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await analyze(page);
  await page
    .getByRole('button', { name: 'Generate workflow from requirements', exact: true })
    .click();
  await expect(page).toHaveURL(/#\/workspace$/);
  await expect(page.getByText('Requirement-based comparison', { exact: true })).toBeVisible();
  expect(requests.analysisRequests).toHaveLength(1);
  expect(requests.planRequests).toHaveLength(1);
  const generated = await getWorkflow(page);
  expect(generated.project.name).toBe(analysisFixture.project_name);
  expect(generated.project.goal).toContain(analysisFixture.tasks[0].title);
  expect(generated.project.members).toHaveLength(3);
  expect(generated.resources).toHaveLength(2);
  expect(
    generated.resources.some((resource: any) => resource.content.includes(requirementText)),
  ).toBe(true);
});

test('editing extracted text invalidates old tasks and sends the reviewed text on reanalysis', async ({
  page,
}) => {
  const requests = await modelFixtures(page);
  await openTemplate(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await analyze(page);
  const preview = page.getByLabel('Extracted requirement text', { exact: true });
  const updatedText = (await preview.inputValue()) + '\nKeep the report under 800 words.';
  await preview.fill(updatedText);
  await expect(page.getByLabel('Task 1 title', { exact: true })).not.toBeVisible();
  await analyze(page);
  expect(requests.analysisRequests).toHaveLength(2);
  expect(requests.analysisRequests[1].document.text).toBe(updatedText);
  expect(requests.planRequests).toHaveLength(0);
});

test('generating from a document preserves unrelated resources and one undo restores the prior workflow', async ({
  page,
}) => {
  await modelFixtures(page);
  await openTemplate(page);
  const original = await getWorkflow(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await uploadPdf(page);
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(
    new RegExp(requirementText),
  );
  await analyze(page);
  await page
    .getByRole('button', { name: 'Generate workflow from requirements', exact: true })
    .click();
  await expect(page.getByText('Requirement-based comparison', { exact: true })).toBeVisible();
  const generated = await getWorkflow(page);
  expect(generated.resources).toEqual(expect.arrayContaining(original.resources));
  expect(generated.project.name).toBe(original.project.name);
  expect(generated.project.members).toEqual(original.project.members);
  await page.getByRole('button', { name: 'Undo (Ctrl+Z)' }).click();
  const undone = await getWorkflow(page);
  expect(undone.project).toEqual(original.project);
  expect(undone.resources).toEqual(original.resources);
  expect(undone.nodes).toEqual(original.nodes);
  expect(undone.edges).toEqual(original.edges);
});
