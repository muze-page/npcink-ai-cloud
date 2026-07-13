import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

const SUBSCRIPTIONS = [
  {
    subscription: {
      subscription_id: 'sub_past_due',
      account_id: 'acct_zeta',
      status: 'past_due',
      plan_id: 'pro',
      plan_version_id: 'pro_v1',
      current_period_start_at: '2026-06-01T00:00:00Z',
      current_period_end_at: '2026-06-30T00:00:00Z',
    },
    account: { account_id: 'acct_zeta', name: 'Zeta Customer' },
    covered_sites: [{ site_id: 'site_zeta', name: 'Zeta Site' }],
    coverage: { site_count: 1, package_alias: 'Pro' },
    latest_billing_snapshots: [{ snapshot_id: 'snap_zeta', totals: { cost: 42.5 } }],
    billing_snapshot_status: {
      status: 'fresh',
      summary: 'Current-period billing statistics are current.',
      fresh_site_count: 1,
      stale_site_count: 0,
      missing_site_count: 0,
    },
  },
  {
    subscription: {
      subscription_id: 'sub_stale',
      account_id: 'acct_beta',
      status: 'active',
      plan_id: 'plus',
      plan_version_id: 'plus_v1',
      current_period_start_at: '2026-07-01T00:00:00Z',
      current_period_end_at: '2026-08-01T00:00:00Z',
    },
    account: { account_id: 'acct_beta', name: 'Beta Customer' },
    covered_sites: [{ site_id: 'site_beta', name: 'Beta Site' }],
    coverage: { site_count: 1, package_alias: 'Plus' },
    latest_billing_snapshots: [{ snapshot_id: 'snap_beta', totals: { cost: 12.25 } }],
    billing_snapshot_status: {
      status: 'stale',
      summary: 'One billing snapshot needs refresh.',
      fresh_site_count: 0,
      stale_site_count: 1,
      missing_site_count: 0,
    },
  },
  {
    subscription: {
      subscription_id: 'sub_stable',
      account_id: 'acct_alpha',
      status: 'active',
      plan_id: 'free',
      plan_version_id: 'free_v1',
      current_period_start_at: '2026-07-01T00:00:00Z',
      current_period_end_at: '2026-09-01T00:00:00Z',
    },
    account: { account_id: 'acct_alpha', name: 'Alpha Customer' },
    covered_sites: [{ site_id: 'site_alpha', name: 'Alpha Site' }],
    coverage: { site_count: 1, package_alias: 'Free' },
    latest_billing_snapshots: [{ snapshot_id: 'snap_alpha', totals: { cost: 0 } }],
    billing_snapshot_status: {
      status: 'fresh',
      summary: 'Current-period billing statistics are current.',
      fresh_site_count: 1,
      stale_site_count: 0,
      missing_site_count: 0,
    },
  },
];

test('subscription risk queue persists server filters and inspector focus while retaining data on refresh failure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  let requestCount = 0;
  let failNextRefresh = false;
  await page.route('**/api/admin/subscriptions?*', async (route) => {
    requestCount += 1;
    if (failNextRefresh) {
      failNextRefresh = false;
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'error', message: 'temporary subscription refresh failure' }),
      });
      return;
    }

    const url = new URL(route.request().url());
    const status = url.searchParams.get('status') || '';
    const accountId = url.searchParams.get('account_id') || '';
    const planId = url.searchParams.get('plan_id') || '';
    const items = SUBSCRIPTIONS.filter((item) => {
      return (!status || item.subscription.status === status) &&
        (!accountId || item.subscription.account_id.includes(accountId)) &&
        (!planId || item.subscription.plan_id.includes(planId));
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', data: { items, total: items.length } }),
    });
  });

  await page.goto('/admin/subscriptions');
  await expect(page.getByRole('heading', { name: /^Service risk queue$|^服务风险队列$/i })).toBeVisible();
  await expect(page.locator('[data-ui="subscription-queue-item"]')).toHaveCount(3);
  await expect(page.locator('table')).toHaveCount(0);
  expect(requestCount).toBe(1);

  const queueItems = page.locator('[data-ui="subscription-queue-item"]');
  await expect(queueItems.nth(0)).toContainText('Zeta Customer');
  await expect(queueItems.nth(1)).toContainText('Beta Customer');
  await expect(page.locator('#subscription-inspector')).toContainText('Zeta Customer');

  await page.getByRole('button', { name: /^Active$|^活跃$|^活躍$/i }).click();
  await expect(page).toHaveURL(/status=active/);
  await expect(queueItems).toHaveCount(2);

  await page.getByPlaceholder(/Account ID|账户 ID|帳戶 ID/i).fill('acct_beta');
  await page.getByPlaceholder(/Plan ID|套餐 ID|方案 ID/i).fill('plus');
  await page.getByRole('button', { name: /^Apply$|^应用$|^套用$/i }).click();
  await expect(page).toHaveURL(/account_id=acct_beta/);
  await expect(page).toHaveURL(/plan_id=plus/);
  await expect(queueItems).toHaveCount(1);

  await page.getByRole('combobox', { name: /Sort page|当前页排序|目前頁排序/i }).selectOption('customer');
  await expect(page).toHaveURL(/sort=customer/);
  const inspectButton = page.getByRole('button', { name: /^Inspect$|^检查$|^檢查$/i });
  await inspectButton.focus();
  await inspectButton.press('Enter');
  await expect(page).toHaveURL(/focus=sub_stale/);
  await expect(page.locator('#subscription-inspector')).toContainText('Beta Customer');

  await page.reload();
  await expect(page.getByPlaceholder(/Account ID|账户 ID|帳戶 ID/i)).toHaveValue('acct_beta');
  await expect(page.getByPlaceholder(/Plan ID|套餐 ID|方案 ID/i)).toHaveValue('plus');
  await expect(page.getByRole('combobox', { name: /Sort page|当前页排序|目前頁排序/i })).toHaveValue('customer');
  await expect(page.locator('#subscription-inspector')).toContainText('Beta Customer');

  failNextRefresh = true;
  await page.getByRole('button', { name: /Refresh subscriptions|刷新订阅|刷新訂閱/i }).click();
  await expect(page.getByText('temporary subscription refresh failure', { exact: true })).toBeVisible();
  await expect(queueItems).toHaveCount(1);
  await expect(page.getByPlaceholder(/Account ID|账户 ID|帳戶 ID/i)).toHaveValue('acct_beta');

  failNextRefresh = true;
  await page.getByPlaceholder(/Account ID|账户 ID|帳戶 ID/i).fill('acct_missing');
  await page.getByRole('button', { name: /^Apply$|^应用$|^套用$/i }).click();
  await expect(page.getByText(/last successfully loaded page|最近一次成功加载的页面/i)).toBeVisible();
  await expect(queueItems).toHaveCount(1);
  await expect(page.locator('#subscription-inspector')).toContainText('Beta Customer');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  await expect(queueItems).toBeVisible();
  const mobileLayout = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(mobileLayout).toEqual({ viewportWidth: 390, scrollWidth: 390 });
});
