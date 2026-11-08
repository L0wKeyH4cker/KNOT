import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
  await page.route(
    /\/api\/(?:plan|requirements\/analyze|connection\/test|credentials|export)$/,
    (route) => route.abort(),
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await expect(page.locator('.block-card')).toHaveCount(8);
});

test('sidebar views share the same shell and preserve edits, canvas and browser navigation', async ({
  page,
}) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await page.getByRole('button', { name: 'Read at 100%', exact: true }).click();
  await expect
    .poll(() => page.locator('.react-flow__viewport').getAttribute('style'))
    .toContain('scale(1)');
  const viewport = await page.locator('.react-flow__viewport').getAttribute('style');
  const positions = await page.locator('.react-flow__node').evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute('data-id'),
      style: (node as HTMLElement).style.transform,
    })),
  );
  await page.evaluate(() => {
    (window as any).__workspaceShell = {
      header: document.querySelector('.app-header'),
      nav: document.querySelector('.rail'),
    };
  });
  for (const [label, panel] of [
    ['Agents', 'agents'],
    ['Project settings', 'project'],
    ['Costs & split', 'billing'],
    ['Saved projects', 'saved'],
    ['Help & shortcuts', 'help'],
  ]) {
    await nav.getByRole('button', { name: label, exact: true }).click();
    await expect(page.getByRole('region', { name: panel, exact: true })).toBeVisible();
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('button', { name: label, exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await expect(page.getByRole('link', { name: 'KNOT home', exact: true })).toHaveCount(1);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(
      await page.evaluate(() => {
        const shell = (window as any).__workspaceShell;
        return (
          shell.header === document.querySelector('.app-header') &&
          shell.nav === document.querySelector('.rail')
        );
      }),
    ).toBe(true);
    if (panel === 'agents')
      await page.getByLabel('Name', { exact: true }).fill('Keep this sidebar edit');
  }
  await nav.getByRole('button', { name: 'Agents', exact: true }).click();
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Keep this sidebar edit');
  await nav.getByRole('button', { name: 'Project settings', exact: true }).click();
  await page.goBack();
  await expect(page.getByRole('region', { name: 'agents', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('region', { name: 'project', exact: true })).toBeVisible();
  await nav.getByRole('button', { name: 'Workflow canvas', exact: true }).click();
  await expect(page.getByTestId('workflow-canvas')).toBeVisible();
  await expect(page.locator('.react-flow__viewport')).toHaveAttribute('style', viewport!);
  expect(
    await page.locator('.react-flow__node').evaluateAll((nodes) =>
      nodes.map((node) => ({
        id: node.getAttribute('data-id'),
        style: (node as HTMLElement).style.transform,
      })),
    ),
  ).toEqual(positions);
});

test('sidebar icons explain themselves on hover and keyboard focus', async ({ page }) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  for (const label of [
    'Workflow canvas',
    'Agents',
    'Project settings',
    'Costs & split',
    'Saved projects',
    'Help & shortcuts',
  ]) {
    const button = nav.getByRole('button', { name: label, exact: true });
    await button.hover();
    await expect(page.getByRole('tooltip')).toContainText(label);
    await page.mouse.move(800, 500);
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await button.focus();
    await expect(page.getByRole('tooltip')).toContainText(label);
    await button.press('Escape');
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await expect(button).toBeFocused();
    await button.blur();
  }
});

test('small screens retain the sidebar while switching views without horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav).toBeVisible();
  for (const [label, panel] of [
    ['Agents', 'agents'],
    ['Project settings', 'project'],
    ['Costs & split', 'billing'],
    ['Saved projects', 'saved'],
    ['Help & shortcuts', 'help'],
  ]) {
    await nav.getByRole('button', { name: label, exact: true }).click();
    await expect(page.getByRole('region', { name: panel, exact: true })).toBeVisible();
    await expect(nav).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
});
