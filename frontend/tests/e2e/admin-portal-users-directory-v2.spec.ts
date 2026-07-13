import { expect, test, type Page, type Route } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

type PortalUserFixture = {
  principal_id: string;
  email: string;
  status: string;
  session_version: number;
  source: string;
  created_at: string;
  last_login_at: string;
  account_id: string;
  account_name: string;
  account_status: string;
  membership_status: string;
  site_id: string;
  site_name: string;
  site_status: string;
  wordpress_url: string;
  subscription_id: string;
  subscription_status: string;
  plan_id: string;
  package_alias: string;
  display_package_label: string;
  qq_bound: boolean;
  qq_binding_count: number;
};

function fixtures(): PortalUserFixture[] {
  return [
    {
      principal_id: 'prn_access_issue', email: 'issue@example.com', status: 'active', session_version: 2, source: 'portal_self_registration', created_at: '2026-07-08T08:00:00Z', last_login_at: '2026-07-09T08:00:00Z', account_id: 'acct_issue', account_name: 'Issue Customer', account_status: 'active', membership_status: 'revoked', site_id: 'site_issue', site_name: 'Issue Site', site_status: 'active', wordpress_url: 'https://issue.example.com', subscription_id: 'sub_issue', subscription_status: 'active', plan_id: 'free', package_alias: 'Free', display_package_label: 'Free', qq_bound: false, qq_binding_count: 0,
    },
    {
      principal_id: 'prn_onboarding', email: 'onboarding@example.com', status: 'active', session_version: 1, source: 'portal_self_registration', created_at: '2026-07-11T08:00:00Z', last_login_at: '', account_id: 'acct_onboarding', account_name: 'Onboarding Customer', account_status: 'active', membership_status: 'active', site_id: 'site_onboarding', site_name: 'Onboarding Site', site_status: 'active', wordpress_url: 'https://onboarding.example.com', subscription_id: 'sub_onboarding', subscription_status: 'active', plan_id: 'free', package_alias: 'Free', display_package_label: 'Free', qq_bound: false, qq_binding_count: 0,
    },
    {
      principal_id: 'prn_active', email: 'active@example.com', status: 'active', session_version: 3, source: 'portal_self_registration', created_at: '2026-07-09T08:00:00Z', last_login_at: '2026-07-12T06:00:00Z', account_id: 'acct_active', account_name: 'Active Customer', account_status: 'active', membership_status: 'active', site_id: 'site_active', site_name: 'Active Site', site_status: 'active', wordpress_url: 'https://active.example.com', subscription_id: 'sub_active', subscription_status: 'active', plan_id: 'pro', package_alias: 'Pro', display_package_label: 'Pro', qq_bound: true, qq_binding_count: 1,
    },
    {
      principal_id: 'prn_disabled', email: 'disabled@example.com', status: 'disabled', session_version: 5, source: 'portal_self_registration', created_at: '2026-07-07T08:00:00Z', last_login_at: '2026-07-08T08:00:00Z', account_id: 'acct_disabled', account_name: 'Disabled Customer', account_status: 'active', membership_status: 'revoked', site_id: 'site_disabled', site_name: 'Disabled Site', site_status: 'active', wordpress_url: 'https://disabled.example.com', subscription_id: 'sub_disabled', subscription_status: 'active', plan_id: 'free', package_alias: 'Free', display_package_label: 'Free', qq_bound: false, qq_binding_count: 0,
    },
  ];
}

async function installPortalUsersMocks(page: Page) {
  await installAdminMocks(page);
  let users = fixtures();
  let requestCount = 0;
  let failNext = false;

  await page.route('**/api/admin/portal-users?*', async (route) => {
    requestCount += 1;
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ status: 'error', message: 'temporary user directory failure' }) });
      return;
    }
    const url = new URL(route.request().url());
    const q = (url.searchParams.get('q') || '').toLowerCase();
    const status = url.searchParams.get('status') || '';
    const packageAlias = (url.searchParams.get('package_alias') || '').toLowerCase();
    const qqBound = url.searchParams.get('qq_bound');
    const items = users.filter((user) => {
      const searchable = [user.email, user.principal_id, user.account_name, user.site_name, user.wordpress_url].join(' ').toLowerCase();
      return (!q || searchable.includes(q)) && (!status || user.status === status) && (!packageAlias || user.package_alias.toLowerCase().includes(packageAlias)) && (qqBound === null || user.qq_bound === (qqBound === 'true'));
    });
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', data: { items, total: items.length, summary: { active: users.filter((user) => user.status === 'active').length, disabled: users.filter((user) => user.status === 'disabled').length, qq_bound: users.filter((user) => user.qq_bound).length, self_registered: users.length }, pagination: { offset: 0, limit: 25, total: items.length, has_more: false } } }) });
  });

  await page.route('**/api/admin/portal-users/*/disable', async (route: Route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const principalId = decodeURIComponent(route.request().url().split('/').at(-2) || '');
    users = users.map((user) => user.principal_id === principalId ? { ...user, status: 'disabled', membership_status: 'revoked', qq_bound: false, qq_binding_count: 0, session_version: user.session_version + 1 } : user);
    const updated = users.find((user) => user.principal_id === principalId)!;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', data: { status: 'disabled', session_version: updated.session_version, receipt: { audit_event_id: 901, event_kind: 'portal_user.disable', scope_kind: 'principal', scope_id: principalId, outcome: 'succeeded', effective_summary: 'Portal access disabled.', audit_filters: { principal_id: principalId } } } }) });
  });

  await page.route('**/api/admin/portal-users/*/audit?*', async (route) => {
    const principalId = decodeURIComponent(route.request().url().split('/').at(-2) || '');
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', data: { principal: { principal_id: principalId, email: users.find((user) => user.principal_id === principalId)?.email, status: 'active', session_version: 2 }, summary: { events: 2, succeeded: 2, failed: 0, registration_events: 1, disable_events: 0 }, items: [{ event_id: 11, event_kind: 'portal.registration', outcome: 'succeeded', actor_kind: 'principal', actor_ref: principalId, method: 'POST', path: '/portal/v1/register', trace_id: 'trace-11', idempotency_key: 'idem-11', scope_kind: 'principal', scope_id: principalId, created_at: '2026-07-08T08:00:00Z' }] } }) });
  });

  return { getRequestCount: () => requestCount, failNextRequest: () => { failNext = true; } };
}

test('Portal user directory persists filters and focus while retaining results on failure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const mocks = await installPortalUsersMocks(page);
  await page.goto('/admin/portal-users');

  await expect(page.getByRole('heading', { name: /Portal user directory|Portal 用户目录/i })).toBeVisible();
  await expect(page.locator('[data-ui="portal-user-directory-item"]')).toHaveCount(4);
  await expect(page.locator('table')).toHaveCount(0);
  expect(mocks.getRequestCount()).toBe(1);

  const rows = page.locator('[data-ui="portal-user-directory-item"]');
  await expect(rows.nth(0)).toContainText('issue@example.com');
  await expect(rows.nth(1)).toContainText('onboarding@example.com');
  await expect(rows.nth(2)).toContainText('active@example.com');
  await expect(page.locator('#portal-user-inspector')).toContainText('issue@example.com');

  await page.getByRole('button', { name: /^Active$|^正常$/i }).click();
  await expect(page).toHaveURL(/status=active/);
  await expect(rows).toHaveCount(3);
  await page.getByLabel(/Search users|搜索用户/i).fill('issue');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/q=issue/);
  await expect(rows).toHaveCount(1);

  const inspect = page.getByRole('button', { name: /^Inspect$|^检查$/i });
  await inspect.focus();
  await inspect.press('Enter');
  await expect(page).toHaveURL(/focus=prn_access_issue/);
  await page.reload();
  await expect(page.getByLabel(/Search users|搜索用户/i)).toHaveValue('issue');
  await expect(page.locator('#portal-user-inspector')).toContainText('issue@example.com');

  mocks.failNextRequest();
  await page.getByLabel(/Search users|搜索用户/i).fill('missing');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page.getByText(/last successfully loaded page|最近一次成功加载的页面/i)).toBeVisible();
  await expect(rows).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('Portal user inspector keeps audit and disable actions contextual and auditable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installPortalUsersMocks(page);
  await page.goto('/admin/portal-users');
  const inspector = page.locator('#portal-user-inspector');

  await expect(inspector.getByRole('button', { name: /^Audit$|^审计$/i })).toBeVisible();
  await expect(inspector.getByRole('button', { name: /^Disable$|^禁用$/i })).toHaveCount(0);
  await inspector.getByRole('button', { name: /^Audit$|^审计$/i }).click();
  const auditDialog = page.getByRole('dialog', { name: /User audit detail|用户审计详情/i });
  await expect(auditDialog).toContainText(/Self registration|自助注册/i);
  await auditDialog.getByRole('button', { name: /^Close$|^关闭$/i }).click();

  await inspector.getByText(/Access actions|访问操作/i).click();
  await inspector.getByRole('button', { name: /^Disable$|^禁用$/i }).click();
  const confirmDialog = page.getByRole('dialog', { name: /Confirm disable user|确认禁用用户/i });
  await confirmDialog.getByRole('button', { name: /^Confirm$|^确认$/i }).click();

  await expect(page.getByText(/was disabled|已禁用/i).first()).toBeVisible();
  await expect(page).toHaveURL(/focus=prn_access_issue/);
  await expect(inspector).toContainText(/Disabled|已禁用/i);
  await expect(page.getByRole('button', { name: /Latest operation|最近操作|最新操作/i })).toBeVisible();
});
