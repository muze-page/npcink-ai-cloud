import { expect, test, type Page, type Route } from '@playwright/test';

const BASE_URL =
  process.env.NPCINK_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.NPCINK_CLOUD_FRONTEND_PORT || '3301'}`;

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'ok', data }),
  });
}

function buildPortalSession(selectedSiteId: string) {
  const sites = [
    {
      site_id: 'site_attention',
      site_name: 'Attention Site',
      account_id: 'acct_portal',
      status: 'provisioning',
      created_at: '2026-04-01T00:00:00Z',
      plan_name: '',
    },
    {
      site_id: 'site_clear',
      site_name: 'Clear Site',
      account_id: 'acct_portal',
      status: 'active',
      created_at: '2026-04-02T00:00:00Z',
      plan_name: 'Growth',
    },
  ];

  const currentSite = sites.find((site) => site.site_id === selectedSiteId) || sites[0];

  return {
    member_ref: 'user:portal-demo@example.com',
    site_id: currentSite.site_id,
    account_id: 'acct_portal',
    identity_type: 'user',
    role: 'user',
    allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
    site: {
      site_id: currentSite.site_id,
      account_id: currentSite.account_id,
      name: currentSite.site_name,
      status: currentSite.status,
      created_at: currentSite.created_at,
    },
    sites,
    accounts: [
      {
        account_id: 'acct_portal',
        name: 'Portal Account',
        status: 'active',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
        membership_status: 'active',
        site_count: 2,
        sites,
      },
    ],
    current_subscription:
      currentSite.site_id === 'site_attention'
        ? {
            subscription_id: 'sub_growth',
            status: 'expired',
            plan_id: 'plan_growth',
            plan_version_id: 'plan_growth_v1',
            current_period_start: '2026-04-01T00:00:00Z',
            current_period_end: '2026-04-12T00:00:00Z',
          }
        : {
            subscription_id: 'sub_growth',
            status: 'active',
            plan_id: 'plan_growth',
            plan_version_id: 'plan_growth_v1',
            current_period_start: '2026-04-01T00:00:00Z',
            current_period_end: '2026-04-30T00:00:00Z',
          },
    entitlements:
      currentSite.site_id === 'site_attention'
        ? {
            requests_limit: 1000,
            tokens_limit: 50000,
            features: ['usage', 'billing'],
          }
        : {
            requests_limit: 2000,
            tokens_limit: 100000,
            features: ['usage', 'billing', 'audit'],
          },
  };
}

async function installPortalMocks(page: Page) {
  let selectedSiteId = 'site_attention';

  await page.context().addCookies([
    {
      name: 'magick_portal_session_token',
      value: 'e2e-portal-session',
      url: BASE_URL,
    },
  ]);

  await page.route(/\/(?:api\/portal|portal\/v1)\/.*/, async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/api\/portal/, '').replace(/^\/portal\/v1/, '');

    if (pathname === '/session') {
      await fulfillJson(route, buildPortalSession(selectedSiteId));
      return;
    }

    if (pathname === '/session/site') {
      const body = route.request().postDataJSON() as { site_id?: string } | null;
      selectedSiteId = body?.site_id || selectedSiteId;
      await fulfillJson(route, buildPortalSession(selectedSiteId));
      return;
    }

    if (pathname === '/sites/site_attention/summary') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
        site: {
          site_id: 'site_attention',
          site_name: 'Attention Site',
          account_id: 'acct_portal',
          status: 'provisioning',
          created_at: '2026-04-01T00:00:00Z',
        },
        covered_by_subscription_id: 'sub_growth',
        subscription_status: 'expired',
        package_alias: 'Pro',
        coverage: {
          subscription_id: 'sub_growth',
          status: 'expired',
          plan_id: 'plan_growth',
          plan_version_id: 'plan_growth_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        entitlement_snapshot: {
          requests_limit: 1000,
          tokens_limit: 50000,
          features: ['usage', 'billing'],
        },
      });
      return;
    }

    if (pathname === '/sites/site_attention/api-keys') {
      await fulfillJson(route, {
        items: [
          {
            key_id: 'key_attention_primary_001',
            site_id: 'site_attention',
            label: 'Attention runtime',
            scopes: ['runtime:execute', 'runtime:resolve'],
            status: 'active',
            created_at: '2026-04-01T00:00:00Z',
            last_used_at: '2026-04-07T09:00:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_clear/summary') {
      await fulfillJson(route, {
        site_id: 'site_clear',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
        site: {
          site_id: 'site_clear',
          site_name: 'Clear Site',
          account_id: 'acct_portal',
          status: 'active',
          created_at: '2026-04-02T00:00:00Z',
        },
        covered_by_subscription_id: 'sub_growth',
        subscription_status: 'active',
        package_alias: '',
        coverage: {
          subscription_id: 'sub_growth',
          status: 'active',
          plan_id: 'plan_growth',
          plan_version_id: 'plan_growth_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-30T00:00:00Z',
        },
        entitlement_snapshot: {
          requests_limit: 2000,
          tokens_limit: 100000,
          features: ['usage', 'billing', 'audit'],
        },
      });
      return;
    }

    if (pathname === '/sites/site_clear/api-keys') {
      await fulfillJson(route, {
        items: [
          {
            key_id: 'key_clear_primary_001',
            site_id: 'site_clear',
            label: 'Clear runtime',
            scopes: ['runtime:execute', 'runtime:resolve', 'catalog:read'],
            status: 'active',
            created_at: '2026-04-02T00:00:00Z',
            last_used_at: '2026-04-07T08:00:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_attention/billing-snapshots') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        items: [
          {
            snapshot_id: 'bill_attention_current',
            site_id: 'site_attention',
            subscription_id: 'sub_growth',
            period_start_at: '2026-04-01T00:00:00Z',
            period_end_at: '2026-04-12T00:00:00Z',
            generated_at: '2026-04-07T10:00:00Z',
            currency: 'USD',
            totals: {
              cost: 18.42,
              runs: 21,
              provider_calls: 21,
              tokens_total: 5000,
            },
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_attention/billing-snapshots/reconciliation') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        snapshot: {
          snapshot_id: 'bill_attention_current',
          generated_at: '2026-04-07T10:00:00Z',
          totals: {
            cost: 18.42,
          },
          plan_version_id: 'plan_growth_v1',
        },
        reconciliation: {
          deltas: {
            cost: 0,
          },
        },
      });
      return;
    }

    if (pathname === '/sites/site_clear/billing-snapshots') {
      await fulfillJson(route, {
        site_id: 'site_clear',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        items: [
          {
            snapshot_id: 'bill_clear_current',
            site_id: 'site_clear',
            subscription_id: 'sub_growth',
            period_start_at: '2026-04-01T00:00:00Z',
            period_end_at: '2026-04-30T00:00:00Z',
            generated_at: '2026-04-07T10:00:00Z',
            currency: 'USD',
            totals: {
              cost: 42.16,
              runs: 55,
              provider_calls: 55,
              tokens_total: 12000,
            },
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_clear/billing-snapshots/reconciliation') {
      await fulfillJson(route, {
        site_id: 'site_clear',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        snapshot: {
          snapshot_id: 'bill_clear_current',
          generated_at: '2026-04-07T10:00:00Z',
          totals: {
            cost: 42.16,
          },
          plan_version_id: 'plan_growth_v1',
        },
        reconciliation: {
          deltas: {
            cost: 0,
          },
        },
      });
      return;
    }

    if (pathname === '/sites/site_attention/usage-summary') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
        timezone: 'Asia/Shanghai',
        generated_at: '2026-04-07T10:00:00Z',
        windows: {
          today: {
            start_at: '2026-04-07T00:00:00Z',
            end_at: '2026-04-07T10:00:00Z',
            runs_total: 8,
            provider_calls_total: 8,
            tokens_in_total: 400,
            tokens_out_total: 1200,
            cost_total: 6.12,
            success_rate: 1.0,
            avg_latency_ms: 380,
          },
          rolling_24h: {
            start_at: '2026-04-06T10:00:00Z',
            end_at: '2026-04-07T10:00:00Z',
            runs_total: 21,
            provider_calls_total: 21,
            tokens_in_total: 1000,
            tokens_out_total: 4000,
            cost_total: 18.42,
            success_rate: 0.98,
            avg_latency_ms: 420,
          },
        },
      });
      return;
    }

    if (pathname === '/sites/site_attention/entitlements') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit', 'manage_site_keys'],
        site: {
          site_id: 'site_attention',
          site_name: 'Attention Site',
          status: 'provisioning',
        },
        subscription: {
          status: 'expired',
          plan_id: 'plan_growth',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        plan_version: {
          plan_id: 'plan_growth',
          version_label: 'v1',
          budgets: {
            max_runs_per_period: 1000,
            max_tokens_per_period: 50000,
            max_cost_per_period: 250,
          },
        },
        entitlement_snapshot: {
          requests_limit: 1000,
          tokens_limit: 50000,
          entitlements: {
            portal: ['usage', 'billing'],
          },
          budgets: {
            max_cost_per_period: 250,
          },
        },
        policy: {},
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-12T00:00:00Z',
        usage_totals: {
          provider_calls: 21,
          tokens_total: 5000,
          cost: 18.42,
        },
        subscription_grace: {
          active: true,
          subscription_status: 'expired',
          grace_period_days: 3,
          grace_until_at: '2026-04-15T00:00:00Z',
        },
        budget_state: {
          runs: {
            current_total: 21,
            limit: 1000,
            over_limit: false,
          },
          tokens: {
            current_total: 5000,
            limit: 50000,
            over_limit: false,
          },
          cost: {
            current_total: 18.42,
            limit: 250,
            over_limit: false,
          },
        },
        generated_at: '2026-04-07T10:00:00Z',
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'error', error: { code: 'not_found' } }),
    });
  });
}

test('portal workspace interaction path: attention strip to filtered table to drawer to usage page', async ({
  page,
}) => {
  await installPortalMocks(page);

  await page.goto('/portal');

  const portalPrimaryNav = page.locator('[data-ui="portal-primary-nav"]');
  await expect(portalPrimaryNav.locator('> a')).toHaveCount(5);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Workspace$|^工作区$|^工作區$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Keys$|^密钥$|^金鑰$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Usage$|^用量$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Package$|^套餐$|^方案$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Sites$|^站点$|^站點$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Audit$|^审计$|^稽核$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Preferences$|^个人偏好$|^偏好設定$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /Package Guide|套餐说明|方案說明/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /Top-up Guide|加量说明|加量說明/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Settings$|^设置$|^設定$/i })).toHaveCount(0);
  await expect(page.getByRole('heading', { level: 1, name: /workspace|工作区/i })).toBeVisible();
  await expect(page.getByText(/Current site|当前站点|目前站點/i).first()).toBeVisible();
  await expect(page.getByText(/Current package|当前套餐|目前方案/i).first()).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: /my sites|站点/i })).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: /current status|当前状态|目前狀態/i })).toBeVisible();
  await expect(page.getByText(/Next action|下一步/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /open keys|打开密钥|打開金鑰/i })).toBeVisible();

  await page.getByRole('button', { name: /attention site.*查看|attention site.*view/i }).first().click();

  await expect(page.getByRole('heading', { level: 2, name: /attention site/i })).toBeVisible();
  await expect(page.locator('a[href="/portal/usage?site=site_attention"]').first()).toBeVisible();

  await page.locator('a[href="/portal/usage?site=site_attention"]').first().click();

  await expect(page).toHaveURL(/\/portal\/usage\?site=site_attention/);
  await expect(page.getByRole('heading', { level: 1, name: /usage|用量/i })).toBeVisible();
  await expect(page.getByRole('combobox').first()).toHaveValue('site_attention');
  await expect(page.getByText(/Requests left|剩余 requests|剩餘 requests/i)).toBeVisible();
  await expect(page.getByText(/Tokens left|剩余 tokens|剩餘 tokens/i)).toBeVisible();
  await expect(page.getByText(/Cost headroom|剩余成本空间|剩餘成本空間/i)).toBeVisible();
});

test('portal workspace surfaces keep one primary action in the header', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal');
  await expect(page.locator('section').first().locator('.btn.btn-primary')).toHaveCount(1);

  await page.goto('/portal/keys?site=site_clear');
  await expect(page.locator('section').first().locator('.btn.btn-primary')).toHaveCount(1);
});

test('portal site record prefers package alias, then formal plan name, before raw plan id', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/sites/site_attention');
  await expect(page.getByText(/^Pro$/).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Preferences|个人偏好|偏好設定/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Audit|审计|稽核/i })).toHaveCount(0);

  await page.goto('/portal/sites/site_clear');
  await expect(page.getByText(/^Growth$/).first()).toBeVisible();
  await expect(page.getByText(/^plan_growth$/)).toHaveCount(0);
});

test('portal package and top-up guides stay secondary and non-transactional', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/usage?site=site_attention');
  await expect(
    page.getByText(
      /Need help understanding limits|需要帮助理解当前限制|需要協助理解目前限制/i
    )
  ).toBeVisible();
  await expect(page.getByText(/checkout|wallet|storefront|buy now/i)).toHaveCount(0);

  await page.goto('/portal/billing?site=site_clear');
  await expect(page.getByText(/Need help\?|需要帮助|需要協助/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Review top-up guidance/i })).toHaveCount(0);
  await expect(page.getByText(/checkout|wallet|storefront|buy now/i)).toHaveCount(0);
});

test('portal usage and workspace stay usable on mobile viewport', async ({ page }) => {
  await installPortalMocks(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/portal');
  await expect(page.getByRole('heading', { level: 1, name: /workspace|工作区/i })).toBeVisible();
  await expect(page.getByText(/Current site|当前站点|目前站點/i).first()).toBeVisible();

  await page.goto('/portal/usage?site=site_attention');
  await expect(page.getByRole('heading', { level: 1, name: /usage|用量/i })).toBeVisible();
  await expect(page.getByText(/Requests left|剩余 requests|剩餘 requests/i)).toBeVisible();
});
