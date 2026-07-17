import { expect, test } from '@playwright/test';
import {
  LONG_ACCOUNT_ID,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

test('subscription detail keeps one PC conclusion and defers operational evidence', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installAdminMocks(page);
  await page.goto('/admin/subscriptions/sub_mvp');

  await expect(page.getByRole('heading', { name: /Service status detail|服务状态详情/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Customer coverage needs follow-up|客户覆盖需要跟进/i })).toHaveCount(1);

  const primaryAction = page.getByRole('link', { name: /Open customer coverage|打开客户覆盖/i });
  await expect(primaryAction).toBeVisible();
  await expect(primaryAction).toHaveAttribute('href', `/admin/accounts/${LONG_ACCOUNT_ID}#coverage-actions`);
  await expect(page.getByRole('link', { name: /Back to subscriptions|返回订阅/i })).toHaveCount(0);

  await expect(page.getByText(/^Read current status and grace posture first\.$/)).toHaveCount(0);
  await expect(page.getByText(/^Open site detail for runtime and entitlement impact\.$/)).toHaveCount(0);
  await expect(page.locator('a[href^="/api/admin/audit-events"]')).toBeHidden();

  const advancedEvidence = page.locator('details').filter({
    hasText: /Advanced subscription evidence|高级订阅运营证据/i,
  });
  await expect(advancedEvidence).not.toHaveAttribute('open', '');
  await expect(page.getByRole('heading', { name: /Package, usage, and service coverage|套餐、用量与服务覆盖/i })).toBeHidden();
  await expect(page.getByRole('heading', { name: /Covered sites|关联站点/i })).toBeHidden();

  await advancedEvidence.locator(':scope > summary').click();
  await expect(page.getByRole('heading', { name: /Package, usage, and service coverage|套餐、用量与服务覆盖/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Covered sites|关联站点/i })).toBeVisible();
});

test('subscription detail failure preserves the PC route shell and bounded retry', async ({ page }) => {
  await installAdminMocks(page);
  await page.unroute('**/api/admin/**');
  let attempts = 0;
  await page.route('**/api/admin/subscriptions/sub_mvp', async (route) => {
    attempts += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiErrorEnvelope('subscription unavailable')),
    });
  });
  await page.goto('/admin/subscriptions/sub_mvp');

  await expect(page.getByRole('heading', { name: /Subscription detail is temporarily unavailable|订阅详情暂时不可用/i })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'subscription unavailable' })).toBeVisible();
  await page.getByRole('button', { name: /^Retry$|^重试$/i }).click();
  await expect.poll(() => attempts).toBe(2);
  await expect(page).toHaveURL(/\/admin\/subscriptions\/sub_mvp$/);
});
