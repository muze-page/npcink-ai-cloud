import { expect, test, type Page, type Route } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

type AccountFixture = {
  account: { account_id: string; name: string; status: string; metadata?: Record<string, unknown> };
  site_count: number;
  active_subscription_count: number;
  top_plan_id: string;
  package_alias: string;
  plan_kind: string;
  display_package_label: string;
  package_kind: string;
  coverage_state: string;
  coverage_follow_up_required: boolean;
  nearest_expiry_at: string;
};

function initialAccounts(): AccountFixture[] {
  return [
    {
      account: { account_id: 'acct_zeta', name: 'Zeta Customer', status: 'suspended', metadata: { operator_note: 'Billing hold' } },
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: 'pro',
      package_alias: 'Pro',
      plan_kind: 'tier_paid',
      display_package_label: 'Pro',
      package_kind: 'tier_package',
      coverage_state: 'covered',
      coverage_follow_up_required: false,
      nearest_expiry_at: '2026-08-01T00:00:00Z',
    },
    {
      account: { account_id: 'acct_beta', name: 'Beta Customer', status: 'active', metadata: { operator_note: 'Assign package before launch' } },
      site_count: 2,
      active_subscription_count: 0,
      top_plan_id: '',
      package_alias: '',
      plan_kind: '',
      display_package_label: 'Uncovered',
      package_kind: 'uncovered',
      coverage_state: 'uncovered',
      coverage_follow_up_required: true,
      nearest_expiry_at: '',
    },
    {
      account: { account_id: 'acct_alpha', name: 'Alpha Customer', status: 'active', metadata: { operator_note: 'Stable customer' } },
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: 'free',
      package_alias: 'Free',
      plan_kind: 'default_free',
      display_package_label: 'Free',
      package_kind: 'formal_free',
      coverage_state: 'covered',
      coverage_follow_up_required: false,
      nearest_expiry_at: '2026-09-01T00:00:00Z',
    },
  ];
}

async function installAccountsQueueMocks(page: Page) {
  await installAdminMocks(page);
  let accounts = initialAccounts();
  let requestCount = 0;
  let failNext = false;

  await page.route('**/api/admin/accounts?*', async (route) => {
    requestCount += 1;
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('temporary customer queue failure')) });
      return;
    }
    const url = new URL(route.request().url());
    const q = (url.searchParams.get('q') || '').toLowerCase();
    const status = url.searchParams.get('status') || '';
    const coverage = url.searchParams.get('coverage_state') || '';
    const packageKind = url.searchParams.get('package_kind') || '';
    const sort = url.searchParams.get('sort') || 'risk';
    let items = accounts.filter((item) => {
      const searchable = [item.account.account_id, item.account.name, item.display_package_label, item.account.metadata?.operator_note].join(' ').toLowerCase();
      return (!q || searchable.includes(q)) && (!status || item.account.status === status) && (!coverage || item.coverage_state === coverage) && (!packageKind || item.package_kind === packageKind);
    });
    const riskRank = (item: AccountFixture) => item.account.status === 'suspended' ? 0 : item.coverage_follow_up_required ? 1 : 3;
    items = [...items].sort((left, right) => {
      if (sort === 'display_name') return left.account.name.localeCompare(right.account.name);
      if (sort === 'created_at') return right.account.account_id.localeCompare(left.account.account_id);
      return riskRank(left) - riskRank(right) || left.account.name.localeCompare(right.account.name);
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope({ items, total: items.length, hidden_internal_total: 1 })),
    });
  });

  await page.route('**/api/admin/accounts', async (route: Route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const payload = route.request().postDataJSON() as Record<string, unknown>;
    const metadata = (payload.metadata || {}) as Record<string, unknown>;
    const bindDefaultFree = Boolean(payload.bind_default_free);
    accounts = [
      ...accounts,
      {
        account: {
          account_id: String(payload.account_id),
          name: String(payload.name),
          status: 'active',
          metadata,
        },
        site_count: 0,
        active_subscription_count: bindDefaultFree ? 1 : 0,
        top_plan_id: bindDefaultFree ? 'free' : '',
        package_alias: bindDefaultFree ? 'Free' : '',
        plan_kind: bindDefaultFree ? 'default_free' : '',
        display_package_label: bindDefaultFree ? 'Free' : 'Uncovered',
        package_kind: bindDefaultFree ? 'formal_free' : 'uncovered',
        coverage_state: bindDefaultFree ? 'covered' : 'uncovered',
        coverage_follow_up_required: false,
        nearest_expiry_at: '',
      },
    ];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({ account_id: payload.account_id })) });
  });

  return {
    getRequestCount: () => requestCount,
    failNextRequest: () => {
      failNext = true;
    },
  };
}

test('customer queue persists risk filters and inspector focus while retaining data on failure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const mocks = await installAccountsQueueMocks(page);

  await page.goto('/admin/accounts');
  await expect(page.getByRole('heading', { name: /Customers and current packages|客户与当前套餐/i })).toBeVisible();
  await expect(page.locator('[data-ui="account-queue-item"]')).toHaveCount(3);
  await expect(page.locator('table')).toHaveCount(0);
  expect(mocks.getRequestCount()).toBe(1);

  const queueItems = page.locator('[data-ui="account-queue-item"]');
  await expect(queueItems.nth(0)).toContainText('Zeta Customer');
  await expect(queueItems.nth(1)).toContainText('Beta Customer');
  await expect(page.locator('#account-inspector')).toContainText('Zeta Customer');

  await page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i).selectOption('uncovered');
  await expect(page).toHaveURL(/coverage_state=uncovered/);
  await expect(queueItems).toHaveCount(1);
  await expect(queueItems).toContainText('Beta Customer');

  await page.getByLabel(/^Search$|^搜索$/i).fill('Beta');
  await page.getByRole('button', { name: /^Apply$|^应用$|^套用$/i }).click();
  await expect(page).toHaveURL(/q=Beta/);
  const inspectButton = page.getByRole('button', { name: /^Inspect$|^检查$|^檢查$/i });
  await inspectButton.focus();
  await inspectButton.press('Enter');
  await expect(page).toHaveURL(/focus=acct_beta/);

  await page.reload();
  await expect(page.getByLabel(/^Search$|^搜索$/i)).toHaveValue('Beta');
  await expect(page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i)).toHaveValue('uncovered');
  await expect(page.locator('#account-inspector')).toContainText('Beta Customer');

  mocks.failNextRequest();
  await page.getByLabel(/^Search$|^搜索$/i).fill('Missing');
  await page.getByRole('button', { name: /^Apply$|^应用$|^套用$/i }).click();
  await expect(page.getByText(/last successfully loaded page|最近一次成功加载的页面/i)).toBeVisible();
  await expect(queueItems).toHaveCount(1);
  await expect(page.locator('#account-inspector')).toContainText('Beta Customer');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('customer creation remains explicit and binds the formal Free package by default', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAccountsQueueMocks(page);
  await page.goto('/admin/accounts');

  await page.getByRole('button', { name: /Add customer|添加客户|新增客戶/i }).click();
  await page.getByLabel(/Account ID|账户 ID|账号 ID|帳戶 ID/i).fill('acct_new_customer_free');
  await page.getByLabel(/^Name$|^名称$|^名稱$/i).fill('New Customer');
  await page.getByLabel(/Operator name|运营显示名|營運顯示名/i).fill('New Customer Display');
  await page.getByLabel(/Operator note|运营备注|營運備註/i).fill('Internal launch note');
  await page.getByRole('button', { name: /Create user|创建用户|建立使用者/i }).click();

  await expect(page.getByText(/User created|用户已创建|使用者已建立/i).first()).toBeVisible();
  await expect(page.getByText('New Customer Display')).toBeVisible();
  await expect(page.getByText('Internal launch note')).toBeVisible();
  await expect(page.getByText('Free').last()).toBeVisible();
});
