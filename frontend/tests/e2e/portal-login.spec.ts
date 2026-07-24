import { expect, test, type Page, type Route } from '@playwright/test';

const BASE_URL =
  process.env.NPCINK_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.NPCINK_CLOUD_FRONTEND_PORT || '3301'}`;

const LOGIN_EMAIL = 'portal-login-e2e@example.com';
const LOGIN_CODE = '246810';
const BASE_HOSTNAME = new URL(BASE_URL).hostname;

async function fulfillJson(route: Route, data: unknown, headers: Record<string, string> = {}) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers,
    body: JSON.stringify({
      status: 'ok',
      error_code: '',
      message: 'ok',
      data,
      meta: { trace_id: 'portal-login-e2e', revision: 'm6' },
    }),
  });
}

async function fulfillError(route: Route, status: number, errorCode: string) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'error',
      error_code: errorCode,
      message: errorCode,
      data: {},
      meta: { trace_id: 'portal-login-e2e', revision: 'm6' },
    }),
  });
}

function buildEmptyPortalSession() {
  return {
    email: LOGIN_EMAIL,
    sites: [],
    selected_context: null,
    auth_mode: 'jwt',
    session: {
      state: 'active',
      transport: 'cookie',
      issued_at: '2026-07-08T00:00:00Z',
      expires_at: '2026-07-08T01:00:00Z',
      revocable: true,
    },
  };
}

async function addPortalSessionCookie(page: Page) {
  await page.context().addCookies([
    {
      name: 'npcink_portal_session_token',
      value: 'e2e-portal-login-session',
      domain: BASE_HOSTNAME,
      path: '/',
      httpOnly: true,
      sameSite: 'Lax',
    },
  ]);
}

async function installLoginFlowMocks(
  page: Page,
  {
    initiallyLoggedIn = false,
    withSessionCookie = initiallyLoggedIn,
  }: { initiallyLoggedIn?: boolean; withSessionCookie?: boolean } = {}
) {
  let loggedIn = initiallyLoggedIn;
  let requestCodeCount = 0;
  let verifyCodeCalled = false;
  let addonConnectionPayload: Record<string, unknown> | null = null;
  let qqStartReturnTo = '';

  await page.route(/\/(?:api\/portal|portal\/v1)\/.*/, async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/api\/portal/, '').replace(/^\/portal\/v1/, '');

    if (pathname === '/session') {
      if (!loggedIn) {
        await fulfillError(route, 401, 'auth.portal_session_required');
        return;
      }
      await fulfillJson(route, buildEmptyPortalSession());
      return;
    }

    if (pathname === '/logout') {
      loggedIn = false;
      await fulfillJson(route, {}, {
        'Set-Cookie': 'npcink_portal_session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax',
      });
      return;
    }

    if (pathname === '/auth/code/request') {
      const body = route.request().postDataJSON() as { email?: string } | null;
      expect(body?.email).toBe(LOGIN_EMAIL);
      requestCodeCount += 1;
      await fulfillJson(route, {
        email: LOGIN_EMAIL,
        delivery: 'development_code',
        expires_in_seconds: 300,
        code: LOGIN_CODE,
      });
      return;
    }

    if (pathname === '/auth/code/verify') {
      const body = route.request().postDataJSON() as {
        email?: string;
        code?: string;
        remember_me?: boolean;
      } | null;
      expect(body?.email).toBe(LOGIN_EMAIL);
      expect(body?.code).toBe(LOGIN_CODE);
      verifyCodeCalled = true;
      loggedIn = true;
      await addPortalSessionCookie(page);
      await fulfillJson(route, buildEmptyPortalSession(), {
        'Set-Cookie':
          'npcink_portal_session_token=e2e-portal-login-session; Path=/; HttpOnly; SameSite=Lax',
      });
      return;
    }

    if (pathname === '/auth/qq/start') {
      qqStartReturnTo = String(url.searchParams.get('return_to') || '');
      expect(url.searchParams.get('intent')).toBe('login');
      await fulfillJson(route, {
        provider: 'qq',
        authorization_url: `${BASE_URL}/qq-authorize-test`,
        state: 'qq-e2e-state',
        expires_in_seconds: 300,
        return_to: qqStartReturnTo,
        intent: 'login',
      });
      return;
    }

    if (pathname === '/auth/identity-providers') {
      await fulfillJson(route, {
        providers: [
          {
            provider: 'qq',
            display_name: 'QQ',
            configured: false,
            bound: false,
            binding: null,
            bind_start_path: '/portal/v1/auth/qq/start',
          },
        ],
      });
      return;
    }

    if (pathname === '/addon-connection-accounts') {
      await fulfillJson(route, {
        items: [
          {
            account_id: 'acct_portal_login_e2e',
            name: 'Portal Login E2E',
            site_count: 0,
          },
        ],
      });
      return;
    }

    if (pathname === '/addon-connections') {
      addonConnectionPayload = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, {
        redirect_url: `${BASE_URL}/wordpress-addon-return?code=exchange-code&state=${String(addonConnectionPayload.state || '')}`,
      });
      return;
    }

    await fulfillError(route, 404, `unhandled:${pathname}`);
  });

  if (withSessionCookie) {
    await addPortalSessionCookie(page);
  }

  return {
    requestCodeCount: () => requestCodeCount,
    verifyCodeCalled: () => verifyCodeCalled,
    addonConnectionPayload: () => addonConnectionPayload,
    qqStartReturnTo: () => qqStartReturnTo,
  };
}

test('QQ is a first-class login entry and preserves the Portal return path', async ({ page }) => {
  const calls = await installLoginFlowMocks(page);

  await page.goto('/portal/login?redirect=/portal/usage');
  await page.getByRole('button', { name: /QQ 登录|QQ login/i }).click();

  await expect(page).toHaveURL(`${BASE_URL}/qq-authorize-test`);
  expect(calls.qqStartReturnTo()).toBe('/portal/usage');
});

test('portal email-code login enters the dashboard after verification', async ({ page }) => {
  const calls = await installLoginFlowMocks(page);

  await page.goto('/portal/login');

  await page.getByLabel(/Email Address|邮箱地址/i).fill(LOGIN_EMAIL);
  await page.getByRole('button', { name: /Send verification code|发送验证码/i }).click();
  await expect(page.getByLabel(/Verification code|验证码/i)).toBeVisible();

  await page.getByRole('button', { name: /Resend code|重发验证码/i }).click();
  await expect(page.getByText(new RegExp(`Verification code resent to ${LOGIN_EMAIL}|验证码已重新发送至 ${LOGIN_EMAIL}`))).toBeVisible();

  await page.getByLabel(/Verification code|验证码/i).fill(LOGIN_CODE);
  await page.getByRole('button', { name: /Verify and continue|验证并继续/i }).click();

  await expect(page).toHaveURL(/\/portal$/);
  await expect(page.getByRole('heading', { name: /No Connected Sites|没有已连接站点/i })).toBeVisible();
  expect(calls.requestCodeCount()).toBe(2);
  expect(calls.verifyCodeCalled()).toBe(true);
});

test('an authenticated user is redirected from the login page to the Portal default', async ({ page }) => {
  await installLoginFlowMocks(page, { initiallyLoggedIn: true });

  await page.goto('/portal/login');

  await expect(page).toHaveURL(`${BASE_URL}/portal`);
  await expect(page.getByRole('heading', { name: /No Connected Sites|没有已连接站点/i })).toBeVisible();
});

test('an authenticated user is redirected from registration to the Portal default', async ({ page }) => {
  await installLoginFlowMocks(page, { initiallyLoggedIn: true });

  await page.goto('/portal/register');

  await expect(page).toHaveURL(`${BASE_URL}/portal`);
  await expect(page.getByRole('heading', { name: /No Connected Sites|没有已连接站点/i })).toBeVisible();
});

test('a stale Portal cookie returns to login without exposing protected navigation', async ({ page }) => {
  await installLoginFlowMocks(page, { withSessionCookie: true });
  const protectedPath = '/portal/usage?window=rolling_24h';

  await page.goto(protectedPath);

  await expect(page).toHaveURL(`${BASE_URL}/portal/login?redirect=${encodeURIComponent(protectedPath)}`);
  await expect(page.locator('[data-ui="portal-primary-nav"]')).toHaveCount(0);
  await expect(page.getByLabel(/Email Address|邮箱地址/i)).toBeVisible();
});

test('addon binding survives login and returns the complete payload to WordPress', async ({ page }) => {
  const calls = await installLoginFlowMocks(page);
  const returnUrl =
    'https://demo.example.com/wp-admin/admin-post.php?action=npcink_cloud_addon_complete_auth&state=addon-state-001';
  const bindingPath = `/portal?${new URLSearchParams({
    connect: 'wordpress-addon',
    site_url: 'https://demo.example.com',
    site_name: 'Demo Site',
    return_url: returnUrl,
    state: 'addon-state-001',
  }).toString()}`;

  await page.goto(bindingPath);
  await expect(page).toHaveURL(`${BASE_URL}/portal/login?redirect=${encodeURIComponent(bindingPath)}`);

  await page.getByLabel(/Email Address|邮箱地址/i).fill(LOGIN_EMAIL);
  await page.getByRole('button', { name: /Send verification code|发送验证码/i }).click();
  await page.getByLabel(/Verification code|验证码/i).fill(LOGIN_CODE);
  await page.getByRole('button', { name: /Verify and continue|验证并继续/i }).click();

  await expect(page).toHaveURL(`${BASE_URL}${bindingPath}`);
  await expect(page.getByRole('heading', { name: /Finish WordPress connection|完成站点绑定/i }).first()).toBeVisible();
  const accountSelect = page.getByLabel(/Customer account|客户账号/i);
  const submitButton = page.getByRole('button', { name: /Finish connection|完成绑定/i });
  await expect(accountSelect).toHaveValue('');
  await expect(accountSelect.locator('option')).toHaveCount(2);
  await expect(submitButton).toBeDisabled();
  expect(calls.addonConnectionPayload()).toBeNull();

  await accountSelect.selectOption('acct_portal_login_e2e');
  await expect(submitButton).toBeEnabled();
  await submitButton.click();
  await expect(page).toHaveURL(/\/wordpress-addon-return\?code=exchange-code&state=addon-state-001/);
  expect(calls.addonConnectionPayload()).toEqual({
    account_id: 'acct_portal_login_e2e',
    site_url: 'https://demo.example.com',
    site_name: 'Demo Site',
    return_url: returnUrl,
    state: 'addon-state-001',
  });
});
