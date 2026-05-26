import { defineConfig } from '@playwright/test';
const port = Number.parseInt(
  String(process.env.MAGICK_AI_CLOUD_FRONTEND_PORT || '3301'),
  10,
);
const baseURL =
  process.env.MAGICK_AI_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${Number.isFinite(port) ? port : 3301}`;
const webServerEnv = {
  ...process.env,
  NEXT_TELEMETRY_DISABLED: '1',
};

if (webServerEnv.NO_COLOR) {
  delete webServerEnv.NO_COLOR;
}

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 90_000,
  expect: {
    timeout: 15_000,
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    },
  },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['line']] : 'list',
  use: {
    baseURL,
    headless: true,
    channel: 'chromium',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: {
      width: 1440,
      height: 1200,
    },
  },
  webServer: {
    command: `pnpm run build && rm -rf .next/standalone/frontend/.next/static .next/standalone/frontend/public && mkdir -p .next/standalone/frontend/.next && cp -R .next/static .next/standalone/frontend/.next/static && if [ -d public ]; then cp -R public .next/standalone/frontend/public; fi && HOSTNAME=127.0.0.1 PORT=${Number.isFinite(port) ? port : 3301} node .next/standalone/frontend/server.js`,
    env: {
      ...webServerEnv,
      HOSTNAME: '127.0.0.1',
      PORT: String(Number.isFinite(port) ? port : 3301),
    },
    url: baseURL,
    reuseExistingServer: false,
    gracefulShutdown: {
      signal: 'SIGTERM',
      timeout: 5_000,
    },
    timeout: 180_000,
  },
});
