import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('a damaged project library preserves the older current project through opening, autosave and reload', async ({
  page,
}) => {
  const current = JSON.parse(
    readFileSync(new URL('../../examples/team-research.json', import.meta.url), 'utf8'),
  );
  current.project.id = 'recoverable-current';
  current.project.name = 'Recoverable project';
  const damagedLibrary = '{damaged project library';
  const modelCalls: string[] = [];
  await page.route(
    /\/api\/(?:plan|credentials|connection\/test|requirements\/analyze)$/,
    (route) => {
      modelCalls.push(route.request().url());
      return route.abort();
    },
  );
  await page.addInitScript(
    ({ current, damagedLibrary }) => {
      if (sessionStorage.getItem('storage-recovery-fixture-seeded')) return;
      localStorage.setItem('knot.current.v1', JSON.stringify(current));
      localStorage.setItem('knot.projects.v1', damagedLibrary);
      localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' }));
      sessionStorage.setItem('storage-recovery-fixture-seeded', 'true');
    },
    { current, damagedLibrary },
  );

  await page.goto('/');
  await page.getByRole('button', { name: /Recoverable project/ }).click();
  await expect(
    page.getByRole('heading', { name: current.project.name, exact: true }),
  ).toBeVisible();
  await expect(page.locator('.block-card')).toHaveCount(current.nodes.length);
  await page.getByTestId('block-research').click();
  await page.getByLabel('Block name', { exact: true }).fill('Recovered task after upgrade');
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const saved = JSON.parse(localStorage.getItem('knot.current.v1') || 'null');
        return saved?.nodes.find((node: { id: string }) => node.id === 'research')?.label;
      }),
    )
    .toBe('Recovered task after upgrade');
  const stored = await page.evaluate(() => ({
    current: JSON.parse(localStorage.getItem('knot.current.v1') || 'null'),
    draft: JSON.parse(localStorage.getItem('knot.project.v1.recoverable-current') || 'null'),
    library: localStorage.getItem('knot.projects.v1'),
  }));
  expect(stored.current.project).toEqual(current.project);
  expect(stored.current.resources).toEqual(current.resources);
  expect(stored.draft).toEqual(stored.current);
  expect(stored.library).toBe(damagedLibrary);

  await page.reload();
  await expect(
    page.getByRole('heading', { name: current.project.name, exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Recovered task after upgrade', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('knot.projects.v1'))).toBe(damagedLibrary);
  expect(modelCalls).toEqual([]);
});
