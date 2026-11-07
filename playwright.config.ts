import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
const chrome =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  (process.platform === 'win32' &&
  existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe')
    ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
    : undefined);
export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 10000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.TEAMBLOCKS_URL || 'http://127.0.0.1:5173',
    viewport: { width: 1600, height: 1000 },
    browserName: 'chromium',
    launchOptions: { executablePath: chrome },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
