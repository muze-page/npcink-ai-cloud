import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

test('site detail keeps the PC first screen focused on one conclusion and one next action', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installAdminMocks(page);
  await page.goto('/admin/sites/site_mvp');

  await expect(page.getByRole('heading', { name: 'MVP Site' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Commercial coverage needs follow-up|商业覆盖需要跟进/i })).toHaveCount(1);
  await expect(page.getByRole('link', { name: /Open coverage|打开覆盖/i })).toBeVisible();
  await expect(page.locator('a[href^="/api/admin/audit-events"]')).toBeHidden();
  // The one remaining unscoped subscriptions link is the persistent sidebar destination.
  await expect(page.locator('a[href="/admin/subscriptions"]')).toHaveCount(1);

  await expect(page.getByText(/Queued or backlogged runs are accumulating\.|当前存在排队或积压运行/i)).toBeVisible();
  await expect(page.getByText(/Open the current customer subscription when commercial coverage is the blocker\./i)).toHaveCount(0);
  await expect(page.getByText(/^Queued$/)).toHaveCount(0);

  const advancedEvidence = page.locator('details').filter({
    hasText: /Advanced site operational evidence|高级站点运营证据/i,
  });
  await expect(advancedEvidence).not.toHaveAttribute('open', '');
  await expect(page.getByRole('heading', { name: /^(Commercial coverage|商业覆盖)$/i })).toBeHidden();
  await advancedEvidence.locator('summary').click();
  await expect(page.getByRole('heading', { name: /^(Commercial coverage|商业覆盖)$/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^(Runtime inspector|运行时检查页)$/i })).toBeVisible();
});

test('site detail failure preserves the PC shell and bounded retry', async ({ page }) => {
  await installAdminMocks(page);
  await page.unroute('**/api/admin/**');
  let attempts = 0;
  await page.route('**/api/admin/sites/site_mvp', async (route) => {
    attempts += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'error', message: 'site unavailable' }),
    });
  });
  await page.goto('/admin/sites/site_mvp');

  await expect(page.getByRole('heading', { name: /Site detail is temporarily unavailable|站点详情暂时不可用/i })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: /Failed to load|加载数据失败/i })).toBeVisible();
  await page.getByRole('button', { name: /^Retry$|^重试$/i }).click();
  await expect.poll(() => attempts).toBe(2);
  await expect(page).toHaveURL(/\/admin\/sites\/site_mvp$/);
});
