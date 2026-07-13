import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

test('runtime diagnostics is telemetry-driven, URL-backed, and mobile safe', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);
  const telemetryRequests: string[] = [];
  let failNextTelemetry = false;
  await page.route('**/api/admin/runtime-telemetry*', async (route) => {
    if (!failNextTelemetry) {
      await route.fallback();
      return;
    }
    failNextTelemetry = false;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ status: 'error', message: 'temporary diagnostic failure' }) });
  });
  page.on('request', (request) => {
    if (request.url().includes('/api/admin/runtime-telemetry')) telemetryRequests.push(request.url());
  });

  await page.goto('/admin/troubleshooting');
  await expect(page.locator('[data-ui="runtime-diagnostic-issue"]')).toHaveCount(1);
  await expect(page.locator('#runtime-diagnostic-inspector')).toContainText(/Provider call coverage gap|供应商调用遥测缺口/i);
  await expect(page.locator('#runtime-diagnostic-inspector a')).toHaveAttribute('href', '#runtime-evidence');
  await expect(page.locator('main input')).toHaveCount(0);

  await page.getByRole('button', { name: '72h' }).click();
  await expect(page).toHaveURL(/window=72/);
  await expect.poll(() => telemetryRequests.some((url) => url.includes('recent_minutes=4320'))).toBe(true);

  await page.getByRole('button', { name: /Provider call coverage gap|供应商调用遥测缺口/i }).click();
  await expect(page).toHaveURL(/focus=hosted_model.provider_call_gap/);
  await expect(page.locator('#runtime-diagnostic-inspector')).toContainText(/Provider call coverage gap|供应商调用遥测缺口/i);
  await page.reload();
  await expect(page.getByRole('button', { name: /Provider call coverage gap|供应商调用遥测缺口/i })).toHaveAttribute('aria-pressed', 'true');

  const metadata = page.locator('#runtime-evidence');
  await expect(metadata).not.toHaveAttribute('open', '');
  await metadata.locator('summary').click();
  await expect(metadata.getByText(/Runtime resolution|运行时解析/i)).toBeVisible();

  failNextTelemetry = true;
  await page.getByRole('button', { name: /^Refresh$|^刷新$/i }).click();
  await expect(page.getByText(/last successfully loaded diagnostic snapshot|最近一次成功加载的诊断快照/i)).toBeVisible();
  await expect(page.locator('[data-ui="runtime-diagnostic-issue"]')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.locator('[data-ui="runtime-diagnostic-issue"]').first()).toBeVisible();
});

test('runtime diagnostics keeps narrow evidence lanes as secondary navigation', async ({ page }) => {
  await installAdminMocks(page);
  await page.goto('/admin/troubleshooting');

  const lanes = page.locator('#evidence-lanes');
  await expect(lanes.locator('a[href="/admin/plugin-observability"]')).toBeVisible();
  await expect(lanes.locator('a[href="/admin/media-observability"]')).toBeVisible();
  await expect(lanes.locator('a[href="/admin/vector-observability"]')).toBeVisible();
  await expect(lanes.locator('a[href="/admin/agent-feedback"]')).toBeVisible();
  await expect(page.getByText(/Groups|分组/)).toHaveCount(0);
});
