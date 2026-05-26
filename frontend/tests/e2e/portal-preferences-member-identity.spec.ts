import { expect, test, type Page, type Route } from '@playwright/test';

const BASE_URL =
  process.env.MAGICK_AI_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.MAGICK_AI_CLOUD_FRONTEND_PORT || '3301'}`;

async function fulfillPortal(route: Route, data: unknown, message = 'ok') {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok',
      message,
      data,
    }),
  });
}

async function installPortalPreferencesMocks(page: Page) {
  let memberPreferences = {
    member_ref: 'user:portal-preferences@example.com',
    locale: 'zh-CN',
    updated_at: '2026-04-08T09:30:00Z',
  };
  let savedLocale = memberPreferences.locale;

  await page.context().addCookies([
    {
      name: 'magick_portal_session_token',
      value: 'e2e-portal-preferences',
      url: BASE_URL,
    },
  ]);

  await page.route(/\/(?:api\/portal|portal\/v1)\/.*/, async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/api\/portal/, '/api/portal').replace(/^\/portal\/v1/, '/api/portal');

    if (pathname === '/api/portal/session') {
      await fulfillPortal(
        route,
        {
          member_ref: 'user:portal-preferences@example.com',
          site_id: 'site_portal_identity',
          account_id: 'acct_portal_identity',
          identity_type: 'user_admin',
          allowed_actions: ['view_sites', 'view_usage'],
          role: 'user_admin',
          auth_mode: 'magic-link',
          sites: [
            {
              site_id: 'site_portal_identity',
              site_name: 'Portal Identity Site',
              account_id: 'acct_portal_identity',
              status: 'active',
              created_at: '2026-04-01T10:00:00Z',
              wordpress_url: 'https://customer.example.com',
            },
          ],
          accounts: [
            {
              account_id: 'acct_portal_identity',
              name: 'Portal Identity Account',
              status: 'active',
              member_ref: 'user:portal-preferences@example.com',
              identity_type: 'user_admin',
              allowed_actions: ['view_sites', 'view_usage'],
              role: 'user_admin',
              membership_status: 'active',
              site_count: 1,
              sites: [],
            },
          ],
        },
        'portal session loaded'
      );
      return;
    }

    if (pathname === '/api/portal/member-summary') {
      await fulfillPortal(
        route,
        {
          member_ref: 'user:portal-preferences@example.com',
          email: 'portal-preferences@example.com',
          auth_mode: 'magic-link',
          identity_type: 'user_admin',
          allowed_actions: ['view_sites', 'view_usage'],
          roles: ['user_admin'],
          accessible_sites_count: 1,
          selected_site_id: 'site_portal_identity',
          memberships: [
            {
              account_id: 'acct_portal_identity',
              identity_type: 'user_admin',
              allowed_actions: ['view_sites', 'view_usage'],
              role: 'user_admin',
              membership_status: 'active',
              site_count: 1,
            },
          ],
        },
        'portal member summary loaded'
      );
      return;
    }

    if (pathname === '/api/portal/member-preferences' && route.request().method() === 'GET') {
      await fulfillPortal(route, memberPreferences, 'portal member preferences loaded');
      return;
    }

    if (pathname === '/api/portal/member-preferences' && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as { locale?: string };
      savedLocale = String(payload.locale || '');
      memberPreferences = {
        ...memberPreferences,
        locale: savedLocale,
        updated_at: '2026-04-08T10:00:00Z',
      };
      await fulfillPortal(route, memberPreferences, 'portal member preferences saved');
      return;
    }

    if (pathname === '/api/portal/sites/site_portal_identity/summary') {
      await fulfillPortal(
        route,
        {
          site_id: 'site_portal_identity',
          account_id: 'acct_portal_identity',
          member_ref: 'user:portal-preferences@example.com',
          identity_type: 'user_admin',
          allowed_actions: ['view_sites', 'view_usage'],
          role: 'user_admin',
          site: {
            site_id: 'site_portal_identity',
            site_name: 'Portal Identity Site',
            account_id: 'acct_portal_identity',
            status: 'active',
            created_at: '2026-04-01T10:00:00Z',
            wordpress_url: 'https://customer.example.com',
          },
          subscription: {
            status: 'active',
            plan_id: 'plan_portal_pro',
            current_period_start_at: '2026-04-01T00:00:00Z',
            current_period_end_at: '2026-05-01T00:00:00Z',
          },
          entitlement_snapshot: {
            requests_limit: 50000,
            tokens_limit: 5000000,
            features: ['portal_summary', 'audit'],
          },
        },
        'portal site summary loaded'
      );
      return;
    }

    await route.abort();
  });

  return {
    getSavedLocale: () => savedLocale,
  };
}

test('portal preferences keep locale writable and move access context behind explicit reveal', async ({ page }) => {
  const portal = await installPortalPreferencesMocks(page);

  await page.goto(`/portal/preferences?site=site_portal_identity`, {
    waitUntil: 'domcontentloaded',
  });

  await expect(page.getByRole('heading', { level: 1, name: /Preferences|个人偏好|個人偏好/i })).toBeVisible();
  await expect(
    page.getByText(
      /Only language preference is editable here|这里仅可调整语言偏好|這裡僅可調整語言偏好/i
    )
  ).toBeVisible();
  await expect(page.getByText(/Current site context|当前站点上下文|目前站點上下文/i)).toHaveCount(0);
  await expect(page.getByText(/Current package|当前套餐|目前方案/i)).toHaveCount(0);
  await expect(page.getByText(/Period End|周期结束|週期結束/i)).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Open Usage|打开用量|打開用量/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Open API Keys|打开密钥|打開金鑰/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Open Package|打开套餐|打開方案/i })).toHaveCount(0);
  await page.getByText(/Access context|访问上下文/i).click();
  await expect(page.getByText('portal-preferences@example.com', { exact: true })).toBeVisible();
  await expect(page.getByText('user:portal-preferences@example.com', { exact: true })).toBeVisible();

  await page.locator('select').last().selectOption('en');
  await page.getByRole('button', { name: /Save|保存/ }).click();

  await expect(page.getByText(/Personal preferences saved|个人偏好已保存|個人偏好已保存/i)).toBeVisible();
  await expect.poll(() => portal.getSavedLocale()).toBe('en');
});
