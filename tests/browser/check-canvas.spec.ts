import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// The introduction is covered separately; this suite exercises canvas rendering.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('knot.onboarding.v1', JSON.stringify({ version: 1, status: 'skipped' })),
  );
});

async function exportedWorkflow(page: Page) {
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  return JSON.parse(readFileSync((await (await download).path())!, 'utf8'));
}

async function visibleGraph(page: Page) {
  await expect(page.locator('.react-flow__node')).toHaveCount(8);
  await expect(page.locator('.react-flow__edge')).toHaveCount(15);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const canvas = document.querySelector('.react-flow')!.getBoundingClientRect();
        return [...document.querySelectorAll('.react-flow__node')].filter((node) => {
          const box = node.getBoundingClientRect();
          return (
            getComputedStyle(node).visibility === 'visible' &&
            box.width > 0 &&
            box.height > 0 &&
            box.right > canvas.left &&
            box.left < canvas.right &&
            box.bottom > canvas.top &&
            box.top < canvas.bottom
          );
        }).length;
      }),
    )
    .toBe(8);
}

test('Check and Back preserve the visible example graph and its measurements across rerenders', async ({
  page,
}) => {
  const modelCalls: string[] = [];
  await page.route(
    /\/api\/(?:plan|credentials|connection\/test|requirements\/analyze)$/,
    (route) => {
      modelCalls.push(route.request().url());
      return route.abort();
    },
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Try the three-person example template' }).click();
  await visibleGraph(page);
  // Wait for the example's initial fit animation and its autosave to finish.
  const initialZoom = JSON.parse(readFileSync(resolve('examples/team-research.json'), 'utf8'))
    .viewport.zoom;
  await page.waitForFunction((initial) => {
    const saved = JSON.parse(localStorage.getItem('knot.current.v1') || 'null');
    return saved?.nodes.length === 8 && saved.viewport.zoom !== initial;
  }, initialZoom);
  const before = await exportedWorkflow(page);
  await visibleGraph(page);

  await page.evaluate(() => {
    const canvas = document.querySelector('.react-flow')!;
    const probe = { hiddenFrames: [] as number[], missingEdges: [] as number[] };
    (window as any).__canvasCheckProbe = probe;
    const observer = new MutationObserver(() => {
      if (canvas.closest('[inert]') || !canvas.isConnected) return;
      const nodes = [...canvas.querySelectorAll('.react-flow__node')];
      const hidden = nodes.filter((node) => getComputedStyle(node).visibility === 'hidden').length;
      if (hidden) probe.hiddenFrames.push(hidden);
      const edges = canvas.querySelectorAll('.react-flow__edge').length;
      if (nodes.length === 8 && edges !== 15) probe.missingEdges.push(edges);
    });
    observer.observe(canvas, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['style'],
    });
  });

  for (let iteration = 0; iteration < 3; iteration++) {
    await page.getByRole('button', { name: 'Check', exact: true }).click();
    await expect(page.getByText('Ready to export your workspace.', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expect(page).toHaveURL(/#\/workspace$/);
    await visibleGraph(page);
  }
  const afterCheck = await exportedWorkflow(page);
  expect(afterCheck).toEqual(before);

  // Selection and another secondary page also rerender the controlled nodes.
  await page.getByTestId('block-research').click();
  await page.getByRole('button', { name: 'Close settings' }).click();
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await visibleGraph(page);
  expect(await exportedWorkflow(page)).toEqual(before);
  expect(await page.evaluate(() => (window as any).__canvasCheckProbe)).toEqual({
    hiddenFrames: [],
    missingEdges: [],
  });
  expect(modelCalls).toEqual([]);
  mkdirSync(resolve('artifacts/browser'), { recursive: true });
  await page.screenshot({
    path: resolve('artifacts/browser/check-back-canvas.png'),
    animations: 'disabled',
  });
});
