import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const template = JSON.parse(
  readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
);
const current = structuredClone(template);
current.project.id = 'library-current-a';
current.project.name = 'Project A';
const other = structuredClone(template);
other.project.id = 'library-other-b';
other.project.name = 'Project B';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ({ current, other }) => {
      if (sessionStorage.getItem('library-fixture-seeded')) return;
      localStorage.setItem('knot.current.v1', JSON.stringify(current));
      localStorage.setItem('knot.projects.v1', JSON.stringify([current, other]));
      localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' }));
      sessionStorage.setItem('library-fixture-seeded', 'true');
    },
    { current, other },
  );
});

async function openOtherTab(page: Page) {
  const opened = page.waitForEvent('popup');
  await page.getByRole('link', { name: 'Open Project B in a new tab', exact: true }).click();
  const tab = await opened;
  await expect(tab.getByRole('heading', { name: 'Project B', exact: true })).toBeVisible();
  return tab;
}

test('a library link opens the selected project in an independent tab and reloads its edits', async ({
  page,
}) => {
  await page.goto('/#/projects');
  const originalUrl = page.url();
  const tab = await openOtherTab(page);
  expect(page.url()).toBe(originalUrl);
  await expect(tab).toHaveURL(/\?project=library-other-b#\/workspace$/);
  await tab.getByRole('button', { name: 'Edit project', exact: true }).click();
  await tab.getByLabel('Project name', { exact: true }).fill('Project B edited');
  await expect
    .poll(async () =>
      tab.evaluate(
        () =>
          JSON.parse(localStorage.getItem('knot.project.v1.library-other-b') || 'null')?.project
            .name,
      ),
    )
    .toBe('Project B edited');
  await tab.getByRole('button', { name: 'Back', exact: true }).click();
  await tab.getByRole('button', { name: 'Save', exact: true }).click();
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!).project.id),
  ).toBe(current.project.id);
  await tab.reload();
  await expect(tab.getByRole('heading', { name: 'Project B edited', exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open Project B edited in a new tab', exact: true }),
  ).toBeVisible();
});

test('reopening the current project uses edits from its other tab instead of overwriting them', async ({
  page,
}) => {
  await page.goto('/#/projects');
  const opened = page.waitForEvent('popup');
  await page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }).click();
  const first = await opened;
  await first.getByRole('button', { name: 'Edit project', exact: true }).click();
  await first.getByLabel('Project name', { exact: true }).fill('Project A updated elsewhere');
  await expect
    .poll(async () =>
      first.evaluate(
        () =>
          JSON.parse(localStorage.getItem('knot.project.v1.library-current-a') || 'null')?.project
            .name,
      ),
    )
    .toBe('Project A updated elsewhere');
  const reopened = page.waitForEvent('popup');
  await page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }).click();
  const second = await reopened;
  await expect(
    second.getByRole('heading', { name: 'Project A updated elsewhere', exact: true }),
  ).toBeVisible();
});

test('the trash button requires confirmation and Cancel or Escape keeps the project', async ({
  page,
}) => {
  await page.goto('/#/projects');
  const before = await page.evaluate(() => localStorage.getItem('knot.projects.v1'));
  await page.getByRole('button', { name: 'Delete Project B', exact: true }).click();
  const confirmation = page.getByRole('alertdialog', { name: 'Delete this project?', exact: true });
  await expect(confirmation).toBeVisible();
  await expect(confirmation.getByText('Project B', { exact: true })).toBeVisible();
  await expect(confirmation.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused();
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(
    page.getByRole('link', { name: 'Open Project B in a new tab', exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('knot.projects.v1'))).toBe(before);
  await page.getByRole('button', { name: 'Delete Project B', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(confirmation).toHaveCount(0);
  await expect(page).toHaveURL(/#\/projects$/);
  expect(await page.evaluate(() => localStorage.getItem('knot.projects.v1'))).toBe(before);
});

test('confirmed deletion removes only the selected project and closes its stale editor', async ({
  page,
}) => {
  await page.goto('/#/projects');
  const tab = await openOtherTab(page);
  await page.getByRole('button', { name: 'Delete Project B', exact: true }).click();
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Delete project', exact: true })
    .click();
  await expect(
    page.getByRole('link', { name: 'Open Project B in a new tab', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }),
  ).toBeVisible();
  await expect(
    tab.getByRole('heading', { name: 'Your project library', exact: true }),
  ).toBeVisible();
  await expect(
    tab.getByText('This project was deleted in another tab.', { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem('knot.project.v1.library-other-b')),
  ).toBeNull();
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!).project.id),
  ).toBe(current.project.id);
  await page.reload();
  await expect(
    page.getByRole('link', { name: 'Open Project B in a new tab', exact: true }),
  ).toHaveCount(0);
});

test('deleting the current project does not re-add it through autosave or reload', async ({
  page,
}) => {
  await page.goto('/#/projects');
  await page.getByRole('button', { name: 'Delete Project A', exact: true }).click();
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Delete project', exact: true })
    .click();
  await expect(
    page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('link', { name: 'Open Project B in a new tab', exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('link', { name: 'Open Project A in a new tab', exact: true }),
  ).toHaveCount(0);
});

test('a missing project link shows the library instead of opening an unrelated project', async ({
  page,
  context,
}) => {
  await page.goto('/#/projects');
  const tab = await context.newPage();
  await tab.goto('/?project=missing-project#/workspace');
  await expect(
    tab.getByRole('heading', { name: 'Your project library', exact: true }),
  ).toBeVisible();
  await expect(
    tab.getByText(
      'This project is no longer available. Choose another project from your library.',
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('knot.current.v1')!).project.id),
  ).toBe(current.project.id);
});
