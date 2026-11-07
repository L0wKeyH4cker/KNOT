import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const steps = [
  ['Meet your team’s workflow', '/workspace'],
  ['Start with small building blocks', '/workspace'],
  ['Decide what happens next', '/workspace'],
  ['Give every task a clear brief', '/workspace'],
  ['Choose the right AI for each job', '/workspace/agents'],
  ['Bring your people and materials', '/workspace/project'],
  ['Let a project brief be your starting point', '/workspace/designer'],
  ['Check your work before exporting', '/workspace/check'],
  ['Take the workflow with you', '/workspace'],
  ['Now make something of your own', '/workspace'],
];

const forbiddenCalls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => {
  const calls: string[] = [];
  forbiddenCalls.set(page, calls);
  await page.route(
    /\/api\/(?:plan|requirements\/analyze|connection\/test|credentials|export)$/,
    async (route) => {
      calls.push(route.request().url());
      await route.abort();
    },
  );
});
test.afterEach(async ({ page }) => expect(forbiddenCalls.get(page)).toEqual([]));

async function start(page: Page) {
  await page.goto('/');
  const example = page.getByRole('button', { name: 'Try the three-person example template' });
  await expect(example).toHaveClass(/example-highlight/);
  await expect(page.getByText('New here? See how it works, step by step.')).toBeVisible();
  await example.click();
  await expect(page.getByTestId('guided-tour')).toBeVisible();
}

test('first-visit tour explains every area, remembers completion and restores the existing project', async ({
  page,
}) => {
  const project = JSON.parse(
    readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
  );
  project.project.id = 'existing-project-before-tour';
  project.project.name = 'Keep my own project';
  project.nodes[0].position.x = 123;
  await page.addInitScript((workflow) => {
    localStorage.setItem('knot.current.v1', JSON.stringify(workflow));
    localStorage.setItem('knot.projects.v1', JSON.stringify([workflow]));
  }, project);
  await start(page);
  const tour = page.getByTestId('guided-tour');
  await expect(page.getByRole('dialog')).toHaveCount(1);
  // Keyboard focus stays in the coachmark, away from the inert editor.
  await expect(tour.getByRole('button', { name: 'Next', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(tour.getByRole('button', { name: 'Back to home', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(tour.getByRole('button', { name: 'Close tour' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(tour.getByRole('button', { name: 'Back to home', exact: true })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(tour.getByRole('button', { name: 'Next', exact: true })).toBeFocused();

  for (let index = 0; index < steps.length; index++) {
    await expect(tour.getByRole('heading', { name: steps[index][0], exact: true })).toBeVisible();
    expect(new URL(page.url()).hash).toBe('#' + steps[index][1]);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!))).toEqual(
      project,
    );
    if (index === 2) {
      await tour.getByRole('button', { name: 'Previous', exact: true }).click();
      await expect(tour.getByRole('heading', { name: steps[1][0], exact: true })).toBeVisible();
      await tour.getByRole('button', { name: 'Next', exact: true }).click();
    }
    if (index < steps.length - 1)
      await tour.getByRole('button', { name: 'Next', exact: true }).click();
  }
  await tour.getByRole('button', { name: 'Back to home', exact: true }).click();
  await expect(page.getByTestId('home-page')).toBeVisible();
  await expect(page.getByLabel('Describe your project')).toBeFocused();
  await expect(page.getByText('Keep my own project', { exact: true })).toBeVisible();
  await expect(page.getByTestId('guided-tour')).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!))).toEqual(
    project,
  );
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('knot.projects.v1')!))).toEqual([
    project,
  ]);
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('knot.onboarding.v1')!).status),
  ).toBe('completed');
  await page.reload();
  await expect(page.locator('.example-highlight')).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!))).toEqual(
    project,
  );
});

test('visitors can return home, replay from help, and leave through native Back', async ({
  page,
}) => {
  await start(page);
  await page
    .getByTestId('guided-tour')
    .getByRole('button', { name: 'Back to home', exact: true })
    .click();
  await expect(page.getByTestId('home-page')).toBeVisible();
  await page.reload();
  await expect(page.locator('.example-highlight')).toHaveCount(0);
  await page.getByRole('button', { name: 'A quick guide', exact: true }).click();
  await page.getByRole('button', { name: 'Take a guided tour' }).click();
  await expect(page.getByTestId('guided-tour')).toBeVisible();
  await page.goBack();
  await expect(page.getByTestId('guided-tour')).toHaveCount(0);
  await expect(page.getByTestId('home-page')).toBeVisible();
});

for (let stepIndex = 0; stepIndex < steps.length; stepIndex++) {
  test(`closing step ${stepIndex + 1} keeps its example page editable and preserves the original project`, async ({
    page,
  }) => {
    const original = JSON.parse(
      readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
    );
    original.project.id = 'original-project-before-close';
    original.project.name = 'Keep this unfinished project';
    original.nodes[0].label = 'Keep my original start';
    await page.addInitScript((workflow) => {
      localStorage.setItem('knot.current.v1', JSON.stringify(workflow));
      localStorage.setItem('knot.projects.v1', '[]');
    }, original);
    await start(page);
    const tour = page.getByTestId('guided-tour');
    for (let index = 0; index < stepIndex; index++)
      await tour.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(
      tour.getByRole('heading', { name: steps[stepIndex][0], exact: true }),
    ).toBeVisible();
    const url = page.url();
    await tour.getByRole('button', { name: 'Close tour', exact: true }).click();
    await expect(tour).toHaveCount(0);
    expect(page.url()).toBe(url);
    expect(await page.locator('#root').evaluate((root) => root.inert)).toBe(false);
    await expect
      .poll(async () =>
        page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!).project.id),
      )
      .not.toBe(original.project.id);
    const library = await page.evaluate(() =>
      JSON.parse(localStorage.getItem('knot.projects.v1')!),
    );
    expect(library.find((project: any) => project.project.id === original.project.id)).toEqual(
      original,
    );
    if (steps[stepIndex][1] === '/workspace') {
      await page.getByTestId('block-research').click();
      await expect(page.getByLabel('Task instructions', { exact: true })).toBeEditable();
    } else if (steps[stepIndex][1] === '/workspace/agents') {
      await expect(page.getByLabel('System prompt', { exact: true })).toBeEditable();
    } else if (steps[stepIndex][1] === '/workspace/project') {
      await expect(page.getByLabel('Project goal', { exact: true })).toBeEditable();
    } else if (steps[stepIndex][1] === '/workspace/designer') {
      await expect(page.getByLabel('Project goal', { exact: true })).toBeEditable();
    } else {
      await expect(
        page.getByRole('button', { name: 'Export runnable ZIP', exact: true }),
      ).toBeEnabled();
    }
  });

  test(`Back to home on step ${stepIndex + 1} restores the original project`, async ({ page }) => {
    const original = JSON.parse(
      readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
    );
    original.project.id = 'original-project-before-home';
    original.project.name = 'Return to my project';
    await page.addInitScript((workflow) => {
      localStorage.setItem('knot.current.v1', JSON.stringify(workflow));
      localStorage.setItem('knot.projects.v1', JSON.stringify([workflow]));
    }, original);
    await start(page);
    const before = await page.evaluate(() => localStorage.getItem('knot.current.v1'));
    const tour = page.getByTestId('guided-tour');
    for (let index = 0; index < stepIndex; index++)
      await tour.getByRole('button', { name: 'Next', exact: true }).click();
    await tour.getByRole('button', { name: 'Back to home', exact: true }).click();
    await expect(tour).toHaveCount(0);
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByLabel('Describe your project')).toBeFocused();
    expect(await page.evaluate(() => localStorage.getItem('knot.current.v1'))).toBe(before);
  });
}

test('Escape closes the coachmark while keeping the current example page', async ({ page }) => {
  await start(page);
  const tour = page.getByTestId('guided-tour');
  for (let index = 0; index < 4; index++)
    await tour.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page).toHaveURL(/#\/workspace\/agents$/);
  await page.keyboard.press('Escape');
  await expect(tour).toHaveCount(0);
  await expect(page).toHaveURL(/#\/workspace\/agents$/);
  await expect(page.getByLabel('System prompt', { exact: true })).toBeEditable();
});

test('the complete tour keeps its controls inside a small viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await start(page);
  const tour = page.getByTestId('guided-tour');
  for (let index = 0; index < steps.length; index++) {
    await expect(tour.getByRole('heading', { name: steps[index][0], exact: true })).toBeVisible();
    await expect
      .poll(async () =>
        page.locator('.tour-card').evaluate((element) => {
          const box = element.getBoundingClientRect();
          return (
            box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight
          );
        }),
      )
      .toBe(true);
    if (index < steps.length - 1)
      await tour.getByRole('button', { name: 'Next', exact: true }).click();
  }
  await tour.getByRole('button', { name: 'Back to home', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('dismissing the welcome cancels an example request still in flight', async ({ page }) => {
  let finishRequest: (() => Promise<void>) | undefined;
  await page.route('**/api/template', async (route) => {
    await new Promise<void>((resolve) => {
      finishRequest = async () => {
        await route.fulfill({
          json: JSON.parse(
            readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
          ),
        });
        resolve();
      };
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect.poll(() => !!finishRequest).toBe(true);
  await page.getByRole('button', { name: 'Skip introduction' }).click();
  await finishRequest!();
  await page.waitForLoadState('networkidle');
  await expect(page.getByTestId('home-page')).toBeVisible();
  await expect(page.getByTestId('guided-tour')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Continue to project setup' })).toBeEnabled();
});
