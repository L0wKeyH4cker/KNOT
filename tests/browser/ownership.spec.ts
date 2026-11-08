import { test, expect, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';

const example = JSON.parse(
  readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
);
const tasks = [
  {
    title: 'Compare venues',
    owner: 'Leo Patel',
    description: 'Compare venues and select a backup.',
    acceptance: 'Include a venue and backup.',
  },
  {
    title: 'Prepare the event-day checklist',
    owner: 'Leo Patel',
    description: 'Prepare the event-day checklist.',
    acceptance: 'Deliver a one-page checklist.',
  },
  {
    title: 'Price supplies',
    owner: 'Nina Brooks',
    description: 'Price the repair supplies.',
    acceptance: 'Include an itemized budget.',
  },
  {
    title: 'Plan volunteer shifts',
    owner: 'Nina Brooks',
    description: 'Plan volunteer shifts for the two-hour event.',
    acceptance: 'Include a volunteer staffing plan.',
  },
  {
    title: 'Draft the outreach plan',
    owner: 'Sam Rivera',
    description: 'Draft registration copy and a promotion schedule.',
    acceptance: 'Include both registration copy and the promotion schedule.',
  },
  {
    title: 'Combine and submit the proposal',
    owner: 'Maya Chen',
    description: 'Combine the three workstreams and submit the approved package.',
    acceptance: 'The proposal includes the venue, budget, staffing, outreach and checklist.',
  },
].map((task) => ({ ...task, source_pages: [1] }));
const analysis = {
  project_name: 'Campus Repair Fair',
  goal: 'Design a free, two-hour campus repair event ready to propose by the end of Day 5.',
  deliverables: ['One event proposal and a one-page event-day checklist'],
  tasks,
  constraints: ['Free event. Two hours. Ready by the end of Day 5.'],
  missing_information: [],
};
const brief = `Campus Repair Fair\n${analysis.goal}\nFinal deliverable: ${analysis.deliverables[0]}\n
Maya Chen — Project lead. Combine the three workstreams and submit the approved package.
Leo Patel — Logistics. Compare venues and prepare the event-day checklist.
Nina Brooks — Budget and staffing. Price supplies and plan volunteer shifts.
Sam Rivera — Outreach. Draft registration copy and a promotion schedule.`;

function plannedWorkflow(project: any, resources: any[], reviewedTasks = tasks) {
  const workflow = structuredClone(example);
  workflow.project = project;
  workflow.resources = resources;
  workflow.viewport = { x: 40, y: 180, zoom: 0.35 };
  workflow.agents = [workflow.agents[0]];
  workflow.nodes = [
    { id: 'start', type: 'start', label: 'Start', position: { x: 0, y: 100 }, config: {} },
    {
      id: 'resources',
      type: 'shared_resource',
      label: 'Project requirements',
      position: { x: 300, y: 100 },
      config: { resource_ids: resources.map((r: any) => r.id) },
    },
    ...reviewedTasks.map((task, i) => ({
      id: `task-${i + 1}`,
      type: 'agent_task',
      label: task.title,
      position: { x: 600 + i * 300, y: 100 },
      config: {
        agent_id: workflow.agents[0].id,
        owner_id: project.members.find((member: any) => member.name === task.owner).id,
        instructions: task.description,
        acceptance: task.acceptance,
        requirement_task_indexes: [i + 1],
        output_format: 'markdown',
        tools: [],
        permissions: { read: [], write: [] },
      },
    })),
    {
      id: 'review',
      type: 'human_review',
      label: 'Approve proposal',
      position: { x: 2400, y: 100 },
      config: {
        owner_id: project.members.find((member: any) => member.name === 'Maya Chen').id,
        instructions: 'Review the combined proposal before submission.',
      },
    },
    {
      id: 'output',
      type: 'output',
      label: 'Event proposal',
      position: { x: 2700, y: 100 },
      config: {
        mappings: [{ source_node: 'task-6', filename: 'proposal.md', format: 'markdown' }],
      },
    },
  ];
  const ids = workflow.nodes.map((node: any) => node.id);
  workflow.edges = ids.slice(1).map((target: string, i: number) => ({
    id: `control-${i}`,
    source: ids[i],
    target,
    source_port: 'out',
    target_port: 'in',
    kind: 'control',
  }));
  for (let i = 1; i <= reviewedTasks.length; i++) {
    workflow.edges.push({
      id: `input-${i}`,
      source: 'resources',
      target: `task-${i}`,
      source_port: 'data-out',
      target_port: 'data-in',
      kind: 'data',
    });
    if (i < reviewedTasks.length)
      workflow.edges.push({
        id: `summary-${i}`,
        source: `task-${i}`,
        target: 'task-6',
        source_port: 'data-out',
        target_port: 'data-in',
        kind: 'data',
      });
  }
  for (const target of ['review', 'output'])
    workflow.edges.push({
      id: `proposal-${target}`,
      source: 'task-6',
      target,
      source_port: 'data-out',
      target_port: 'data-in',
      kind: 'data',
    });
  return workflow;
}

async function exported(page: Page) {
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  return JSON.parse(readFileSync((await (await download).path())!, 'utf8'));
}

function assignments(workflow: any) {
  return Object.fromEntries(
    workflow.nodes
      .filter((node: any) => node.type === 'agent_task')
      .map((node: any) => [
        node.label,
        workflow.project.members.find((member: any) => member.id === node.config.owner_id)?.name,
      ]),
  );
}

async function expectMembersOverview(
  page: Page,
  expectedOwners: Record<string, string>,
  reviewer: string,
) {
  const overview = page.getByRole('region', { name: 'Members overview', exact: true });
  await expect(overview).toBeVisible();
  await expect(overview.getByText('Edit ownership in each block’s settings.')).toBeVisible();
  await expect(overview.getByRole('textbox')).toHaveCount(0);
  const names = [...new Set([...Object.values(expectedOwners), reviewer])];
  await expect(overview.getByRole('article')).toHaveCount(names.length);
  for (const name of names) {
    const member = overview.getByRole('article', { name: `Member ${name}`, exact: true });
    await expect(member.getByText(name, { exact: true })).toBeVisible();
    const ownedTasks = Object.entries(expectedOwners).filter(([, owner]) => owner === name);
    for (const [title, owner] of Object.entries(expectedOwners))
      await expect(member.getByText(title, { exact: true })).toHaveCount(owner === name ? 1 : 0);
    await expect(member.getByText(/Research partner/)).toHaveCount(ownedTasks.length);
    await expect(member.getByText('Approve proposal', { exact: true })).toHaveCount(
      name === reviewer ? 1 : 0,
    );
    await expect(member.getByText('Human review', { exact: true })).toHaveCount(
      name === reviewer ? 1 : 0,
    );
  }
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ok: true, planner_credentials: { OPENAI_API_KEY: true } } }),
  );
});

test('requirements replace the default three people with four named owners and generation can be undone (model fixtures)', async ({
  page,
}) => {
  await page.route('**/api/requirements/analyze', (route) => route.fulfill({ json: { analysis } }));
  let planRequest: any;
  await page.route('**/api/plan', async (route) => {
    planRequest = route.request().postDataJSON();
    const resource = planRequest.resources.find((r: any) =>
      r.id.startsWith('requirements-analysis-'),
    );
    await route.fulfill({
      json: {
        workflow: plannedWorkflow(
          planRequest.project,
          planRequest.resources,
          JSON.parse(resource.content).tasks,
        ),
      },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  const original = await exported(page);
  await page.getByRole('button', { name: 'AI designer', exact: true }).click();
  await page.getByTestId('requirements-file-input').setInputFiles({
    name: 'campus-repair-fair.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(brief),
  });
  await expect(page.getByLabel('Extracted requirement text', { exact: true })).toHaveValue(brief);
  await page.getByLabel('Planning model', { exact: true }).fill('fixture-only');
  await page.getByRole('button', { name: 'Analyze requirements', exact: true }).click();
  for (const [i, task] of tasks.entries())
    await expect(page.getByLabel(`Task ${i + 1} owner`, { exact: true })).toHaveValue(task.owner);
  await page.getByLabel('Task 5 owner', { exact: true }).fill('  Sam Rivera  ');
  await page
    .getByRole('button', { name: 'Generate workflow from requirements', exact: true })
    .click();
  await expect(page.locator('.block-card')).toHaveCount(10);
  const generated = await exported(page);
  expect(generated.project.members.map((member: any) => member.name).sort()).toEqual([
    'Leo Patel',
    'Maya Chen',
    'Nina Brooks',
    'Sam Rivera',
  ]);
  expect(assignments(generated)).toEqual(
    Object.fromEntries(tasks.map((task) => [task.title, task.owner])),
  );
  expect(planRequest.project.members).toEqual(generated.project.members);
  expect(planRequest.project.goal).toContain('Owner: Sam Rivera');
  await page.getByRole('button', { name: 'Project settings', exact: true }).click();
  await expectMembersOverview(
    page,
    Object.fromEntries(tasks.map((task) => [task.title, task.owner])),
    'Maya Chen',
  );
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  for (const [i, task] of tasks.entries()) {
    await page.getByTestId(`block-task-${i + 1}`).click();
    await expect(page.getByLabel('Human owner', { exact: true })).toHaveValue(task.owner);
    if (i === 4) {
      mkdirSync('artifacts/browser', { recursive: true });
      const dismiss = page.getByRole('button', { name: 'Dismiss notification', exact: true });
      if (await dismiss.isVisible()) await dismiss.click();
      await page.screenshot({
        path: 'artifacts/browser/requirements-owners.png',
        fullPage: true,
        animations: 'disabled',
      });
    }
    await page.getByRole('button', { name: 'Close settings' }).click();
  }
  await page.getByRole('button', { name: 'Undo (Ctrl+Z)' }).click();
  const undone = await exported(page);
  expect(undone.project).toEqual(original.project);
  expect(undone.nodes).toEqual(original.nodes);
  expect(undone.resources).toEqual(original.resources);
});

test('task and review owners can be edited directly, reuse existing people and persist without changing other tasks', async ({
  page,
}) => {
  const project = {
    ...example.project,
    id: 'repair-fair-owner-editor',
    name: 'Campus Repair Fair',
    members: [...new Set(tasks.map((task) => task.owner))].map((name, i) => ({
      id: `person-${i}`,
      name,
      skills: '',
    })),
  };
  const workflow = plannedWorkflow(project, example.resources);
  await page.addInitScript((initial) => {
    if (!localStorage.getItem('knot.current.v1')) {
      localStorage.setItem('knot.current.v1', JSON.stringify(initial));
      localStorage.setItem('knot.projects.v1', JSON.stringify([initial]));
    }
  }, workflow);
  await page.goto('/#/workspace');
  await page.getByTestId('block-task-1').click();
  const owner = page.getByLabel('Human owner', { exact: true });
  await expect(owner).toHaveValue('Leo Patel');
  await owner.fill('');
  await owner.press('Enter');
  await expect(page.getByText('Enter an owner name.', { exact: true })).toBeVisible();
  await expect(owner).toHaveValue('');
  await owner.fill('Sam Rivera');
  await owner.press('Enter');
  await page.getByRole('button', { name: 'Close settings' }).click();
  const reassigned = await exported(page);
  expect(reassigned.project.members).toHaveLength(4);
  expect(assignments(reassigned)['Compare venues']).toBe('Sam Rivera');
  expect(assignments(reassigned)['Prepare the event-day checklist']).toBe('Leo Patel');
  expect(assignments(reassigned)['Draft the outreach plan']).toBe('Sam Rivera');
  await page.getByRole('button', { name: 'Project settings', exact: true }).click();
  await expectMembersOverview(
    page,
    {
      ...Object.fromEntries(tasks.map((task) => [task.title, task.owner])),
      'Compare venues': 'Sam Rivera',
    },
    'Maya Chen',
  );
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('button', { name: 'Undo (Ctrl+Z)' }).click();
  expect(assignments(await exported(page))).toEqual(assignments(workflow));

  await page.getByTestId('block-task-1').click();
  await owner.fill('Alex Morgan');
  await page.getByLabel('Block name', { exact: true }).click();
  await page.getByRole('button', { name: 'Close settings' }).click();
  await page.getByTestId('block-review').click();
  await page.getByLabel('Reviewer', { exact: true }).fill('Alex Morgan');
  await page.getByLabel('Reviewer', { exact: true }).press('Enter');
  await page.getByRole('button', { name: 'Close settings' }).click();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.reload();
  const saved = await exported(page);
  expect(saved.project.members).toHaveLength(5);
  const alex = saved.project.members.find((member: any) => member.name === 'Alex Morgan');
  expect(saved.nodes.find((node: any) => node.id === 'task-1').config.owner_id).toBe(alex.id);
  expect(saved.nodes.find((node: any) => node.id === 'review').config.owner_id).toBe(alex.id);
  expect(assignments(saved)['Prepare the event-day checklist']).toBe('Leo Patel');
  expect(assignments(saved)['Combine and submit the proposal']).toBe('Maya Chen');
  await page.getByTestId('block-task-1').click();
  await expect(owner).toHaveValue('Alex Morgan');
  await page.getByRole('button', { name: 'Close settings' }).click();
  await page.getByRole('button', { name: 'Project settings', exact: true }).click();
  await expectMembersOverview(
    page,
    {
      ...Object.fromEntries(tasks.map((task) => [task.title, task.owner])),
      'Compare venues': 'Alex Morgan',
    },
    'Alex Morgan',
  );
});
