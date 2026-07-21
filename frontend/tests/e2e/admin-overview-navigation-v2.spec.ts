import { expect, test } from '@playwright/test';
import {
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

test('admin overview keeps canonical work destinations primary and evidence collapsed', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);
  await page.goto('/admin');

  await expect(page.locator('[data-ui="admin-overview-destination"]')).toHaveCount(4);
  await expect(page.locator('[data-ui="admin-overview-destination"][href="/admin/accounts"]')).toBeVisible();
  await expect(page.locator('[data-ui="admin-overview-destination"][href="/admin/coverage"]')).toBeVisible();
  await expect(page.locator('[data-ui="admin-overview-destination"][href="/admin/support-requests"]')).toBeVisible();
  await expect(page.locator('[data-ui="admin-overview-destination"][href="/admin/troubleshooting"]')).toBeVisible();
  await expect(page.locator('[data-ui="admin-overview-destinations"] a[href="/admin/ai-resources"]')).toHaveCount(0);
  await expect(page.locator('[data-ui="admin-overview-destinations"] a[href="/admin/service-settings"]')).toHaveCount(0);

  const extendedEvidence = page.locator('details').filter({
    hasText: /Platform usage and extended evidence|平台用量与扩展证据/i,
  });
  await expect(extendedEvidence).not.toHaveAttribute('open', '');
  await expect(page.getByRole('heading', { name: /Runtime and usage snapshot|运行与用量快照/i })).toBeHidden();
  await testInfo.attach('p4-e03-admin-overview', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('quick switcher discovers diagnostic child routes without expanding the sidebar', async ({ page }) => {
  await installAdminMocks(page);
  await page.goto('/admin');

  await expect(page.locator('[data-ui="admin-primary-nav"] a[href="/admin/media-observability"]')).toHaveCount(0);
  const switcherButton = page.getByRole('button', { name: /Open quick switcher|打开快速跳转/i });
  await switcherButton.click();
  const dialog = page.getByRole('dialog', { name: /Quick switcher|快速跳转/i });
  const input = dialog.locator('input');
  await input.fill('media');
  await expect(dialog.locator('a[href="/admin/media-observability"]')).toBeVisible();
  await expect(dialog.getByText(/Diagnostics|诊断/i)).toBeVisible();

  await input.fill('feedback');
  await expect(dialog.locator('a[href="/admin/agent-feedback"]')).toBeVisible();
  await input.fill('vector');
  await expect(dialog.locator('a[href="/admin/vector-observability"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(switcherButton).toBeFocused();
});

test('admin overview API failure preserves the page shell and safe retry', async ({ page }) => {
  await installAdminMocks(page);
  await page.unroute('**/api/admin/**');
  await page.route('**/api/admin/overview', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify(
        buildAdminApiErrorEnvelope(
          'overview unavailable',
          'admin.overview_unavailable'
        )
      ),
    });
  });
  await page.goto('/admin');

  await expect(page.getByRole('heading', { name: /Platform state comes first|先看平台概况/i })).toBeVisible();
  await expect(page.locator('[role="alert"]').filter({ hasText: /overview unavailable/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Retry$|^重试$/i })).toBeVisible();
});
