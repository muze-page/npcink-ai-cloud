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
      name: 'npcink_portal_session_token',
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

    if (pathname === '/auth/identity-providers') {
      await fulfillJson(route, {
        principal_id: 'prn_8d95fab64fa7487bb31cd81c3adac4a8',
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

    if (pathname === '/sites/site_attention/monitoring-overview') {
      await fulfillJson(route, {
        contract_version: 'magick-site-monitoring-overview-v1',
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        generated_at: '2026-04-07T10:00:00Z',
        window: {
          hours: 24,
          start_at: '2026-04-06T10:00:00Z',
          end_at: '2026-04-07T10:00:00Z',
        },
        health: {
          status: 'warning',
          score: 72,
          summary: '1 monitoring area should be reviewed.',
          components_count: 3,
        },
        action_required: [
          {
            code: 'plugin_observability.plugin_error',
            severity: 'warning',
            source: 'plugins',
            title: 'Plugin error detected',
            detail: 'Adapter reported wordpress.fatal_error.',
            suggested_action: 'Open plugin monitoring.',
            sort_weight: 30,
          },
        ],
        quota: {
          period_start_at: '2026-04-01T00:00:00Z',
          period_end_at: '2026-04-12T00:00:00Z',
          runs: { used: 21, limit: 1000, remaining: 979, usage_ratio: 0.021, over_limit: false },
          tokens: { used: 5000, limit: 50000, remaining: 45000, usage_ratio: 0.1, over_limit: false },
          cost: { used: 18.42, limit: 250, remaining: 231.58, usage_ratio: 0.073, over_limit: false },
          top_pressure: 'none',
          summary: 'Quota is within current limits.',
        },
        activity: {
          last_seen_at: '2026-04-07T09:00:00Z',
          plugin_events_total: 24,
          plugin_errors_total: 2,
          media_jobs_total: 4,
          media_failed_total: 0,
          vector_searches_total: 8,
          vector_no_hit_total: 1,
          runtime_runs_total: 21,
          runtime_success_rate: 0.98,
          runtime_p95_latency_ms: 520,
        },
        components: [
          {
            component: 'plugins',
            status: 'warning',
            score: 70,
            summary: 'Plugin telemetry reports recent errors.',
          },
          {
            component: 'media',
            status: 'ok',
            score: 92,
            summary: 'Media processing is healthy.',
          },
          {
            component: 'vector',
            status: 'ok',
            score: 88,
            summary: 'Site knowledge search is healthy.',
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_attention/diagnostic-advisor') {
      await fulfillJson(route, {
        advisor_version: 'internal-ai-advisor-v1',
        scope: 'site_diagnostics',
        status: 'attention',
        severity: 'warning',
        headline: 'Site diagnostics need review',
        summary: '1 prioritized recommendation is ready for operator review.',
        evidence: [],
        recommended_actions: [
          {
            action: 'inspect_plugin_observability_attention',
            requires_operator: true,
          },
        ],
        confidence: 'high',
        filters: {
          site_id: 'site_attention',
          window_hours: 24,
        },
        signals: [],
        diagnostic_items: [
          {
            diagnostic_key: 'plugin_attention:e2e_plugin_runtime_failure',
            code: 'plugin_observability.plugin_error',
            severity: 'warning',
            source: 'plugins',
            title: 'Adapter runtime failure',
            evidence_summary: 'Adapter reported wordpress.fatal_error.',
            likely_cause: 'Plugin telemetry reports active errors.',
            next_step: 'Open Plugins and inspect recent errors.',
            recommended_action_id: 'inspect_plugin_observability_attention',
            workflow_status: 'new',
            status_detail: {
              workflow_status: 'new',
              status_source: 'monitoring_signal',
              allowed_statuses: ['new', 'acknowledged', 'muted', 'resolved'],
              muted_until: '',
              operator_note: '',
              updated_at: '2026-04-07T10:00:00Z',
            },
            evidence_window: {
              hours: 24,
              start_at: '2026-04-06T10:00:00Z',
              end_at: '2026-04-07T10:00:00Z',
            },
            last_updated_at: '2026-04-07T10:00:00Z',
            operator_review_required: true,
            direct_wordpress_write: false,
          },
        ],
        diagnostic_workflow: {
          new: 1,
          acknowledged: 0,
          muted: 0,
          resolved: 0,
          total: 1,
          needs_attention: 1,
          allowed_statuses: ['new', 'acknowledged', 'muted', 'resolved'],
        },
        evidence_window: {
          hours: 24,
          start_at: '2026-04-06T10:00:00Z',
          end_at: '2026-04-07T10:00:00Z',
        },
        safety: {
          write_posture: 'suggestion_only',
          direct_wordpress_write: false,
          operator_review_required: true,
          automatic_repair_allowed: false,
          raw_payload_exposed: false,
        },
        generated_at: '2026-04-07T10:00:00Z',
      });
      return;
    }

    if (pathname === '/sites/site_attention/plugin-observability') {
      await fulfillJson(route, {
        contract_version: 'magick-plugin-observability-v1',
        site_id: 'site_attention',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        role: 'user',
        generated_at: '2026-04-07T10:00:00Z',
        window: {
          hours: 24,
          start_at: '2026-04-06T10:00:00Z',
          end_at: '2026-04-07T10:00:00Z',
        },
        totals: {
          events_total: 24,
          ok_total: 22,
          error_total: 2,
          success_rate: 0.92,
          avg_latency_ms: 410,
          last_seen_at: '2026-04-07T09:00:00Z',
        },
        health: {
          status: 'warning',
          score: 70,
          summary: 'Plugin telemetry reports recent errors.',
          reasons: ['wordpress.fatal_error'],
        },
        attention: [],
        attention_workflow: {
          active: 0,
          acknowledged: 0,
          muted: 0,
          resolved: 0,
          total: 0,
          needs_attention: 0,
        },
        digest: {
          period_label: 'Last 24h',
          window_hours: 24,
          headline: 'Plugin errors need review',
          bullets: ['Adapter reported wordpress.fatal_error.'],
          top_plugin_slug: 'magick-ai-adapter',
          top_error_code: 'wordpress.fatal_error',
        },
        plugins: [],
        timeline: [],
        errors: [],
        recent_errors: [],
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

    if (pathname === '/sites/site_attention/credit-ledger') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-12T00:00:00Z',
        rate_version: 'portal-e2e-v1',
        pagination: {
          limit: 12,
          offset: 0,
          total: 1,
          has_more: false,
        },
        summary: {
          total_credits: 120,
          consumed_credits: 18,
          granted_credits: 120,
          net_used_credits: 18,
          entry_count: 1,
        },
        items: [
          {
            ledger_entry_id: 'ledger_attention_001',
            site_id: 'site_attention',
            source_type: 'runtime',
            category: 'hosted_runtime',
            category_label: 'Hosted runtime',
            explanation: 'Runtime execution credits',
            credit_delta: -18,
            consumed_credits: 18,
            net_credit_delta: -18,
            quantity: 21,
            unit: 'run',
            rate: 1,
            rate_unit: 'run',
            rate_version: 'portal-e2e-v1',
            created_at: '2026-04-07T09:30:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_attention/credit-packs') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        catalog_version: 'portal-e2e-v1',
        period_policy: 'current_period',
        grant_event_type: 'credit_pack_purchase',
        items: [
          {
            pack_id: 'pack_small',
            label: 'Small credit pack',
            ai_credits: 100,
            amount: 19,
            currency: 'USD',
            active: true,
            period_policy: 'current_period',
            grant_event_type: 'credit_pack_purchase',
            catalog_version: 'portal-e2e-v1',
          },
        ],
      });
      return;
    }

    if (pathname === '/sites/site_attention/payment-orders') {
      await fulfillJson(route, {
        site_id: 'site_attention',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        pagination: {
          limit: 8,
          offset: 0,
          total: 0,
          has_more: false,
        },
        items: [],
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
  await expect(portalPrimaryNav.locator('> a')).toHaveCount(4);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Overview$|^概览$|^概覽$|^Workspace$|^工作区$|^工作區$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Plan and usage$|^套餐与用量$|^套餐與用量$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Sites and domain$|^站点与域名$|^站點與網域$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Contact$|^联系方式$|^聯絡方式$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Billing$|^账单$|^帳單$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Monitoring$|^监控$|^監控$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^AI Insights$|^AI 分析$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Keys$|^密钥$|^金鑰$/i })).toHaveCount(0);
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
  await expect(page.getByRole('link', { name: /open site|查看站点|查看站點/i }).first()).toBeVisible();

  await page.getByRole('button', { name: /attention site.*查看|attention site.*view/i }).first().click();

  await expect(page.getByRole('heading', { level: 2, name: /attention site/i })).toBeVisible();
  await expect(page.locator('a[href="/portal/usage?site=site_attention"]').first()).toBeVisible();

  await page.locator('a[href="/portal/usage?site=site_attention"]').first().click();

  await expect(page).toHaveURL(/\/portal\/usage\?site=site_attention/);
  await expect(page.getByRole('heading', { level: 1, name: /Plan and usage|套餐与用量|usage|用量|当前周期用量/i })).toBeVisible();
  await expect(page.getByRole('combobox').first()).toHaveValue('site_attention');
  await expect(page.getByText(/Requests left|剩余请求|剩余 requests|剩餘 requests/i)).toBeVisible();
  await expect(page.getByText(/Tokens left|剩余 tokens|剩餘 tokens/i)).toBeVisible();
  await expect(page.getByText(/Cost headroom|成本余量|剩余成本空间|剩餘成本空間/i)).toBeVisible();
});

test('portal workspace keeps one primary action and sites keeps add action secondary', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal');
  await expect(page.locator('section').first().locator('.btn.btn-primary')).toHaveCount(1);

  await page.goto('/portal/sites?site=site_clear');
  await expect(page.locator('section').first().locator('.btn.btn-primary')).toHaveCount(0);
  await expect(page.locator('section').first().locator('.btn.btn-secondary')).toHaveCount(1);
  await expect(page.getByRole('button', { name: /add site|添加站点|新增站點/i })).toBeVisible();
});

test('portal contact page hides internal identifiers by default', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/account');
  await expect(page.getByRole('heading', { level: 1, name: /Contact|联系方式|聯絡方式/i })).toBeVisible();
  await expect(page.locator('[data-portal-account="contact-info"]')).toHaveCount(1);
  await expect(page.locator('[data-portal-account="support-details"]')).toHaveCount(1);
  await expect(page.locator('[data-portal-account="support-details"]')).not.toHaveAttribute('open', /.+/);
  await expect(page.getByText(/portal-demo@example\.com/i).first()).toBeVisible();
  await expect(page.getByText(/prn_8d95fab64fa7487bb31cd81c3adac4a8/i)).toHaveCount(0);
  await expect(page.getByText(/acct_portal/i)).not.toBeVisible();
});

test('portal monitoring shows diagnostic advisor and routes to plugin evidence', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/monitoring?site=site_attention');

  await expect(page.getByRole('heading', { name: /site diagnostics/i })).toBeVisible();
  await expect(page.getByText(/suggestion only/i)).toBeVisible();
  await expect(page.getByText(/no direct wordpress write/i)).toBeVisible();
  await expect(page.getByText(/^New$/i).first()).toBeVisible();
  await expect(page.getByText(/Evidence window/i)).toBeVisible();
  await expect(page.getByText(/Adapter runtime failure/i)).toBeVisible();
  await expect(page.getByText(/^new$/i).first()).toBeVisible();

  await page.getByRole('button', { name: /Adapter runtime failure/i }).click();

  await expect(page).toHaveURL(/\/portal\/monitoring\?site=site_attention&tab=plugins/);
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
