import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000';

export default defineConfig({
  testDir: './e2e',
  outputDir: 'test-results',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-ci',
      // responsive.spec.ts is mobile-viewport-only (it exercises the
      // mobile-only nav toggle, hidden by CSS above the 768px breakpoint —
      // it cannot pass under a Desktop Chrome viewport) — it belongs to
      // mobile-ci alone, matching that project's own testMatch below.
      testIgnore: /smoke-production\.spec\.ts|responsive\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-ci',
      testMatch: /responsive\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'deployed-smoke',
      testMatch: /smoke-production\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Production build+start, never `next dev`: Turbopack's dev server has
  // been observed to intermittently 403 its own on-demand-compiled JS
  // chunks under concurrent first-load requests (reproduced locally —
  // the login page's own chunk 403'd, leaving the app stuck on
  // "Initializing Fortress…" forever, which is what actually failed every
  // fixture-based test in CI, not a Playwright/test-code issue). A
  // production server serves pre-built, static chunks with no such
  // per-request compile step, and better matches what "production-safe"
  // E2E should exercise anyway.
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : {
    command: 'npm run build && npm run start',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 300_000,
  },
});
