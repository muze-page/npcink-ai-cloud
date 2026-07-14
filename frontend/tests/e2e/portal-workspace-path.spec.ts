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

async function installPortalMocks(
  page: Page,
  options: { paymentReturnFlow?: boolean; emptyCreditTrend?: boolean } = {}
) {
  let selectedSiteId = 'site_attention';
  const canceledPaymentOrderIds = new Set<string>();
  let paymentReturnPollCount = 0;
  let paymentReturnConfirmed = false;

  await page.context().addCookies([
    {
      name: 'npcink_portal_session_token',
      value: 'e2e-portal-session',
      url: BASE_URL,
    },
  ]);

  await page.context().route('https://pay.example.com/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><title>Mock Alipay checkout</title>',
    });
  });

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

    if (pathname === '/account/usage-summary') {
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
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

    if (pathname === '/account/entitlements') {
      const paidRemaining = paymentReturnConfirmed ? 10000 : 0;
      const packageRemaining = 2419;
      const totalRemaining = packageRemaining + paidRemaining;
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
        member_ref: 'user:portal-demo@example.com',
        identity_type: 'user',
        role: 'user',
        allowed_actions: ['view_sites', 'view_usage', 'view_billing', 'view_audit'],
        site: {
          site_id: '',
          site_name: '',
          status: 'active',
        },
        subscription: {
          status: 'active',
          plan_id: 'plan_growth',
          plan_version_id: 'plan_growth_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-30T00:00:00Z',
        },
        plan_version: {
          plan_id: 'plan_growth',
          version_label: 'v1',
          budgets: {
            max_ai_credits_per_period: 3000,
            max_runs_per_period: 1000,
            max_tokens_per_period: 50000,
            max_cost_per_period: 250,
          },
        },
        entitlement_snapshot: {
          requests_limit: 1000,
          tokens_limit: 50000,
          features: ['usage', 'billing'],
          entitlements: {
            portal: ['usage', 'billing'],
          },
          budgets: {
            max_ai_credits_per_period: 3000,
            max_cost_per_period: 250,
          },
        },
        policy: {},
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-30T00:00:00Z',
        usage_totals: {
          provider_calls: 21,
          tokens_total: 5000,
          cost: 18.42,
        },
        subscription_grace: {
          active: false,
          subscription_status: 'active',
        },
        budget_state: {
          ai_credits: {
            current_total: 581,
            limit: 3000,
            over_limit: false,
          },
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
        quota_summary: {
          status: 'ok',
          period_start_at: '2026-04-01T00:00:00Z',
          period_end_at: '2026-04-30T00:00:00Z',
          generated_at: '2026-04-07T10:00:00Z',
          credit: {
            key: 'ai_credits',
            used: 581,
            limit: 581 + totalRemaining,
            remaining: totalRemaining,
            unlimited: false,
            unit: 'credits',
            package_limit: 3000,
            package_remaining: packageRemaining,
            paid_remaining: paidRemaining,
            paid_grant_count: paidRemaining > 0 ? 1 : 0,
            paid_next_expires_at: paidRemaining > 0 ? '2027-04-07T10:00:00Z' : '',
            total_remaining: totalRemaining,
          },
          credit_ledger_summary: {
            consumed_credits: 612,
            granted_credits: 0,
            adjustment_credits: 0,
            refund_credits: 0,
            net_credit_delta: -612,
            net_used_credits: 612,
            entry_count: 24,
          },
          resource_limits: [
            {
              key: 'bound_sites',
              used: 2,
              limit: 1,
              remaining: 0,
              status: 'limited',
            },
            {
              key: 'vector_documents',
              used: 0,
              limit: 100,
              remaining: 100,
              status: 'ok',
            },
          ],
        },
        generated_at: '2026-04-07T10:00:00Z',
      });
      return;
    }

    if (pathname === '/account/credit-trend') {
      const trendWindow = url.searchParams.get('window') || '24h';
      const pointCount = trendWindow === '1h' ? 12 : trendWindow === '24h' ? 24 : trendWindow === '7d' ? 7 : 30;
      const bucketSeconds = trendWindow === '1h' ? 300 : trendWindow === '24h' ? 3600 : 86400;
      const endAt = new Date('2026-04-07T10:00:00Z').getTime();
      const points = Array.from({ length: pointCount }, (_, index) => {
        const pointEnd = endAt - (pointCount - index - 1) * bucketSeconds * 1000;
        const pointStart = pointEnd - bucketSeconds * 1000;
        const credits = options.emptyCreditTrend
          ? 0
          : index === pointCount - 1
            ? 18
            : index === pointCount - 2
              ? 6
              : 0;
        return {
          start_at: new Date(pointStart).toISOString(),
          end_at: new Date(pointEnd).toISOString(),
          credits,
          entry_count: credits > 0 ? 1 : 0,
        };
      });
      await fulfillJson(route, {
        contract_version: 'portal-credit-trend-v1',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        site_id: url.searchParams.get('site_id') || '',
        window: trendWindow,
        bucket_seconds: bucketSeconds,
        start_at: points[0]?.start_at || '',
        end_at: points.at(-1)?.end_at || '',
        total_credits: points.reduce((total, point) => total + point.credits, 0),
        entry_count: points.reduce((total, point) => total + point.entry_count, 0),
        points,
      });
      return;
    }

    if (pathname === '/account/credit-ledger') {
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-30T00:00:00Z',
        rate_version: 'portal-e2e-v1',
        pagination: {
          limit: 12,
          offset: 0,
          total: 1,
          has_more: false,
        },
        summary: {
          total_credits: 3000,
          consumed_credits: 581,
          granted_credits: 3000,
          net_used_credits: 581,
          entry_count: 1,
        },
        items: [
          {
            ledger_entry_id: 'ledger_account_001',
            site_id: 'site_attention',
            source_type: 'runtime',
            category: 'hosted_runtime',
            category_label: 'AI usage',
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

    if (pathname === '/account/credit-events') {
      await fulfillJson(route, {
        contract_version: 'portal-credit-events-v1',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-30T00:00:00Z',
        filters: {
          window: url.searchParams.get('window') || 'period',
          site_id: url.searchParams.get('site_id') || '',
          feature: url.searchParams.get('feature') || '',
        },
        summary: { event_count: 1, consumed_credits: 18 },
        pagination: { limit: 20, offset: 0, total: 1, has_more: false },
        items: [{
          event_id: 'run:run_portal_001',
          support_reference: 'run_portal_001',
          site_id: 'site_attention',
          feature_key: 'content_generation',
          feature_label: 'Content writing',
          feature_detail: 'The site used AI to draft, revise, or organize content.',
          created_at: '2026-04-07T10:00:00Z',
          net_credit_delta: -18,
          consumed_credits: 18,
          direction: 'consumed',
          component_count: 2,
          components: [
            { key: 'request', credits: 3 },
            { key: 'model_processing', credits: 15 },
          ],
        }],
      });
      return;
    }

    if (pathname === '/account/credit-event-buckets') {
      await fulfillJson(route, {
        contract_version: 'portal-credit-event-buckets-v1',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        period_start_at: '2026-04-01T00:00:00Z',
        period_end_at: '2026-04-30T00:00:00Z',
        bucket: url.searchParams.get('bucket') || '30m',
        bucket_seconds: 1800,
        timezone: 'UTC',
        filters: {
          window: url.searchParams.get('window') || '7d',
          site_id: url.searchParams.get('site_id') || '',
          feature: url.searchParams.get('feature') || '',
        },
        summary: { bucket_count: 1, consumed_credits: 18 },
        pagination: { limit: 20, offset: 0, total: 1, has_more: false },
        items: [{
          bucket_id: '30m:986594',
          start_at: '2026-04-07T09:30:00Z',
          end_at: '2026-04-07T10:00:00Z',
          consumed_credits: 18,
          event_count: 1,
          site_count: 1,
          top_feature_key: 'content_generation',
          feature_totals: [{ feature_key: 'content_generation', consumed_credits: 18, event_count: 1 }],
        }],
      });
      return;
    }

    if (pathname === '/account/credit-packs') {
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
        catalog_version: 'portal-e2e-v1',
        period_policy: 'current_period',
        grant_event_type: 'credit_pack_purchase',
        items: [
          {
            pack_id: 'pack_small',
            label: 'Small credit pack',
            ai_credits: 10000,
            amount: 99,
            currency: 'CNY',
            validity_days: 180,
            active: true,
            period_policy: 'current_period',
            grant_event_type: 'credit_pack_purchase',
            catalog_version: 'portal-e2e-v1',
          },
        ],
      });
      return;
    }

    if (pathname === '/account/credit-pack-orders' && route.request().method() === 'POST') {
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
        order: {
          order_id: 'pay_credit_pack_new_tab',
          account_id: 'acct_portal',
          provider: 'alipay',
          status: 'pending',
          amount: 99,
          currency: 'CNY',
          subject: 'Npcink AI Cloud 小积分包（10,000 AI 积分）',
          checkout_url: 'https://pay.example.com/pay_credit_pack_new_tab',
          available_actions: ['continue_payment', 'cancel'],
          purchase_kind: 'credit_pack',
          credit_pack: {
            pack_id: 'pack_small',
            label: 'Small credit pack',
            ai_credits: 10000,
            amount: 99,
            currency: 'CNY',
          },
          status_detail: { code: 'awaiting_payment_confirmation' },
          created_at: '2026-04-07T10:05:00Z',
        },
      });
      return;
    }

    const paymentOrderCancellation = pathname.match(
      /^\/account\/payment-orders\/([^/]+)\/cancellation$/
    );
    if (paymentOrderCancellation && route.request().method() === 'POST') {
      const orderId = decodeURIComponent(paymentOrderCancellation[1]);
      canceledPaymentOrderIds.add(orderId);
      await fulfillJson(route, {
        account_id: 'acct_portal',
        order: {
          order_id: orderId,
          account_id: 'acct_portal',
          provider: 'alipay',
          status: 'canceled',
          amount: 99,
          currency: 'CNY',
          subject: 'Small credit pack',
          checkout_url: '',
          available_actions: [],
          purchase_kind: 'credit_pack',
          status_detail: { code: 'canceled' },
          created_at: '2026-04-07T09:00:00Z',
        },
      });
      return;
    }

    const paymentOrderDetail = pathname.match(/^\/account\/payment-orders\/([^/]+)$/);
    if (paymentOrderDetail && route.request().method() === 'GET') {
      const orderId = decodeURIComponent(paymentOrderDetail[1]);
      if (options.paymentReturnFlow && orderId === 'pay_return_polling') {
        paymentReturnPollCount += 1;
        const status = paymentReturnPollCount >= 2 ? 'paid' : 'pending';
        paymentReturnConfirmed = status === 'paid';
        await fulfillJson(route, {
          account_id: 'acct_portal',
          order: {
            order_id: orderId,
            account_id: 'acct_portal',
            provider: 'alipay',
            status,
            amount: 0.01,
            currency: 'CNY',
            subject: 'Npcink AI Cloud 小积分包（10,000 AI 积分）',
            checkout_url: '',
            available_actions: status === 'pending' ? ['cancel'] : [],
            purchase_kind: 'credit_pack',
            credit_pack: {
              pack_id: 'pack_small',
              label: 'Small credit pack',
              ai_credits: 10000,
              amount: 0.01,
              currency: 'CNY',
            },
            status_detail: {
              code: status === 'paid' ? 'paid_and_granted' : 'awaiting_payment_confirmation',
            },
            created_at: '2026-04-07T10:00:00Z',
            paid_at: status === 'paid' ? '2026-04-07T10:01:00Z' : '',
          },
        });
        return;
      }
    }

    if (pathname === '/account/payment-orders') {
      const creditPackCanceled = canceledPaymentOrderIds.has('pay_pending_visible');
      const statusGroup = new URL(route.request().url()).searchParams.get('status_group') || 'all';
      const allOrders = [
        {
          order_id: 'pay_plus_pending',
          account_id: 'acct_portal',
          provider: 'alipay',
          status: 'pending',
          amount: 15,
          currency: 'CNY',
          subject: 'Npcink AI Cloud Plus 月度套餐',
          checkout_url: 'https://pay.example.com/pay_plus_pending',
          available_actions: ['continue_payment', 'cancel'],
          purchase_kind: 'subscription_plan',
          expires_at: '2026-04-07T10:30:00Z',
          metadata: {
            subscription_order_id: 'sord_plus_pending',
            target_tier_id: 'plus',
          },
          status_detail: {
            code: 'awaiting_payment_confirmation',
          },
          created_at: '2026-04-07T10:00:00Z',
        },
        {
          order_id: 'pay_pending_visible',
          account_id: 'acct_portal',
          provider: 'alipay',
          status: creditPackCanceled ? 'canceled' : 'pending',
          amount: 99,
          currency: 'CNY',
          subject: 'Npcink AI Cloud 小积分包（10,000 AI 积分）',
          available_actions: creditPackCanceled ? [] : ['cancel'],
          purchase_kind: 'credit_pack',
          credit_pack: {
            pack_id: 'pack_small',
            label: 'Small credit pack',
          },
          status_detail: {
            code: creditPackCanceled ? 'canceled' : 'awaiting_payment_confirmation',
          },
          created_at: '2026-04-07T09:00:00Z',
        },
        {
          order_id: 'pay_expired_visible',
          account_id: 'acct_portal',
          provider: 'alipay',
          status: 'canceled',
          amount: 349,
          currency: 'CNY',
          subject: 'Medium credit pack',
          available_actions: [],
          purchase_kind: 'credit_pack',
          status_detail: {
            code: 'expired_unpaid',
          },
          created_at: '2026-04-06T09:00:00Z',
        },
      ];
      const groupedOrders = allOrders.filter((order) => {
        if (statusGroup === 'pending') return order.status === 'pending';
        if (statusGroup === 'paid') return order.status === 'paid';
        if (statusGroup === 'closed') return ['canceled', 'refunded'].includes(order.status);
        return true;
      });
      const counts = {
        all: allOrders.length,
        pending: allOrders.filter((order) => order.status === 'pending').length,
        paid: allOrders.filter((order) => order.status === 'paid').length,
        closed: allOrders.filter((order) => ['canceled', 'refunded'].includes(order.status)).length,
      };
      await fulfillJson(route, {
        site_id: '',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        status_group: statusGroup,
        counts,
        visibility: {
          canceled_orders_visible_days: 7,
          database_records_deleted: false,
        },
        pagination: {
          limit: 10,
          offset: 0,
          total: groupedOrders.length,
          has_more: false,
        },
        items: groupedOrders,
      });
      return;
    }

    if (pathname === '/account/plan-offers') {
      await fulfillJson(route, {
        account_id: 'acct_portal',
        principal_id: 'principal_portal',
        trial: { available: true, trial_days: 14 },
        comparison_tiers: [
          {
            tier_id: 'free', label: 'Free', plan_id: 'free', plan_version_id: 'free_v1',
            monthly_points: 300, site_limit: 1, knowledge_article_limit: 100, concurrency_limit: 1, batch_item_limit: 5,
            comparison_rights: {
              monthly_points: { state: 'limited', value: 300 }, site_limit: { state: 'limited', value: 1 },
              knowledge_article_limit: { state: 'limited', value: 100 }, concurrency_limit: { state: 'limited', value: 1 },
              batch_item_limit: { state: 'limited', value: 5 },
            },
            amount: null, currency: 'CNY', billing_cycle: null, purchase_mode: 'included',
          },
          {
            tier_id: 'plus', label: 'Plus', plan_id: 'plus', plan_version_id: 'plus_v1',
            monthly_points: 3000, site_limit: 3, knowledge_article_limit: null, concurrency_limit: 2, batch_item_limit: 15,
            comparison_rights: {
              monthly_points: { state: 'limited', value: 3000 }, site_limit: { state: 'limited', value: 3 },
              knowledge_article_limit: { state: 'unconfigured', value: null }, concurrency_limit: { state: 'limited', value: 2 },
              batch_item_limit: { state: 'limited', value: 15 },
            },
            amount: 15, currency: 'CNY', billing_cycle: 'monthly', purchase_mode: 'self_serve',
          },
          {
            tier_id: 'pro', label: 'Pro', plan_id: 'pro', plan_version_id: 'pro_v1',
            monthly_points: 10000, site_limit: 5, knowledge_article_limit: 2000, concurrency_limit: 3, batch_item_limit: 25,
            comparison_rights: {
              monthly_points: { state: 'limited', value: 10000 }, site_limit: { state: 'limited', value: 5 },
              knowledge_article_limit: { state: 'limited', value: 2000 }, concurrency_limit: { state: 'limited', value: 3 },
              batch_item_limit: { state: 'limited', value: 25 },
            },
            amount: 29, currency: 'CNY', billing_cycle: 'monthly', purchase_mode: 'self_serve',
          },
        ],
        items: [
          {
            offer_id: 'plus_monthly_v1',
            plan_id: 'plus',
            plan_version_id: 'plus_v1',
            tier_id: 'plus',
            billing_cycle: 'monthly',
            amount: 15,
            currency: 'CNY',
            purchase_mode: 'self_serve',
            status: 'active',
            trial_enabled: true,
            trial_days: 14,
            trial_credit_limit: 3000,
            trial_requires_approval: false,
          },
          {
            offer_id: 'pro_monthly_v1',
            plan_id: 'pro',
            plan_version_id: 'pro_v1',
            tier_id: 'pro',
            billing_cycle: 'monthly',
            amount: 29,
            currency: 'CNY',
            purchase_mode: 'self_serve',
            status: 'active',
            trial_enabled: true,
            trial_days: 14,
            trial_credit_limit: 5000,
            trial_requires_approval: false,
          },
        ],
      });
      return;
    }

    if (pathname === '/support-requests') {
      await fulfillJson(route, {
        summary: {
          open: 1,
          in_progress: 0,
          resolved: 0,
          closed: 0,
        },
        pagination: {
          limit: 50,
          offset: 0,
          total: 1,
          has_more: false,
        },
        items: [
          {
            request_id: 'ticket_portal_e2e_open',
            account_id: 'acct_portal',
            topic: 'billing',
            status: 'open',
            title: 'Payment order status looks wrong',
            description: 'Please check the latest account payment order.',
            created_at: '2026-04-07T09:05:00Z',
            updated_at: '2026-04-07T09:05:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/account/audit-summary') {
      await fulfillJson(route, {
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        totals: {
          events: 12,
          succeeded: 12,
          error: 0,
        },
        groups: [
          {
            event_kind: 'portal_magic_link.consumed',
            outcome: 'success',
            count: 1,
            first_seen_at: '2026-04-07T09:00:00Z',
            last_seen_at: '2026-04-07T09:00:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/account/audit-events') {
      const limit = Number(url.searchParams.get('limit') || 10);
      const events = Array.from({ length: 12 }, (_, index) => ({
        event_id: `audit_portal_${String(index + 1).padStart(3, '0')}`,
        event_kind: index === 0 ? 'portal_magic_link.consumed' : 'run',
        outcome: 'success',
        created_at: `2026-04-07T09:${String(index).padStart(2, '0')}:00Z`,
        trace_id: index === 0 ? 'trace_portal_e2e' : '',
      }));
      await fulfillJson(route, {
        account_id: 'acct_portal',
        items: events.slice(0, limit),
      });
      return;
    }

    if (
      pathname === '/sites/site_attention/vector-observability'
      || pathname === '/sites/site_clear/vector-observability'
    ) {
      const isClearSite = pathname.includes('site_clear');
      await fulfillJson(route, {
        contract_version: 'magick-vector-observability-summary-v1',
        site_id: isClearSite ? 'site_clear' : 'site_attention',
        account_id: 'acct_portal',
        generated_at: '2026-04-07T10:00:00Z',
        window: {
          hours: 168,
          start_at: '2026-03-31T10:00:00Z',
          end_at: '2026-04-07T10:00:00Z',
        },
        totals: {
          index_jobs_total: isClearSite ? 3 : 0,
          index_succeeded_total: isClearSite ? 3 : 0,
          index_failed_total: 0,
          index_success_rate: isClearSite ? 1 : 0,
          accepted_documents_total: isClearSite ? 86 : 0,
          indexed_documents_total: isClearSite ? 86 : 0,
          indexed_chunks_total: isClearSite ? 214 : 0,
          failed_documents_total: 0,
          deleted_entries_total: 0,
          avg_index_duration_ms: 0,
          p95_index_duration_ms: 0,
          last_index_job_finished_at: isClearSite ? '2026-04-07T09:30:00Z' : '',
          search_queries_total: isClearSite ? 32 : 0,
          search_succeeded_total: isClearSite ? 32 : 0,
          search_failed_total: 0,
          search_success_rate: isClearSite ? 1 : 0,
          no_hit_total: isClearSite ? 3 : 0,
          no_hit_rate: isClearSite ? 0.09375 : 0,
          avg_search_latency_ms: 0,
          p95_search_latency_ms: 0,
          avg_top1_score: 0,
          avg_result_score: 0,
          last_search_finished_at: isClearSite ? '2026-04-07T09:45:00Z' : '',
          active_site_count: isClearSite ? 1 : 0,
          indexed_site_count: isClearSite ? 1 : 0,
          current_document_count: isClearSite ? 86 : 0,
          current_chunk_count: isClearSite ? 214 : 0,
        },
        health: {
          status: isClearSite ? 'ok' : 'inactive',
          score: isClearSite ? 100 : 0,
          summary: '',
        },
        timeline: [],
        intents: [],
        index_snapshots: isClearSite
          ? [{
              site_id: 'site_clear',
              document_count: 86,
              chunk_count: 214,
              post_type_counts: { post: 80, page: 6 },
              source_type_counts: { wordpress: 86 },
              last_indexed_at: '2026-04-07T09:30:00Z',
              embedding_provider: 'hidden-from-portal',
              embedding_model: 'hidden-from-portal',
              embedding_dimensions: 1024,
              vector_backend: 'hidden-from-portal',
              captured_at: '2026-04-07T09:30:00Z',
            }]
          : [],
        errors: [],
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
        customer_status: {
          status: 'degraded',
          needs_attention: true,
          issue_count: 1,
          generated_at: '2026-04-07T10:00:00Z',
        },
        generated_at: '2026-04-07T10:00:00Z',
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
            validity_days: 90,
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

test('portal workspace interaction path: account overview to site drawer and service pages', async ({
  page,
}) => {
  await installPortalMocks(page);

  await page.goto('/portal');

  const portalPrimaryNav = page.locator('[data-ui="portal-primary-nav"]');
  await expect(portalPrimaryNav.locator('> a')).toHaveCount(5);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Service$|^服务$|^服務$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Package$|^套餐$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Usage$|^用量$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Tickets$|^工单$|^工單$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Account$|^账号$|^帳號$/i })).toBeVisible();
  await expect(portalPrimaryNav.getByRole('link', { name: /^Billing$|^账单$|^帳單$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Monitoring$|^监控$|^監控$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^AI Insights$|^AI 分析$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Keys$|^密钥$|^金鑰$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Audit$|^审计$|^稽核$/i })).toHaveCount(0);
  await expect(portalPrimaryNav.getByRole('link', { name: /^Settings$|^设置$|^設定$/i })).toHaveCount(0);
  await expect(page.getByRole('heading', { level: 1, name: /my service|我的服务|服務/i })).toBeVisible();
  await expect(page.getByText(/Current package|当前套餐|目前方案/i).first()).toBeVisible();
  await expect(page.getByText(/2,419|2419/i).first()).toBeVisible();
  await expect(page.getByText(/Tickets|工单|工單/i).first()).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: /my sites|站点/i })).toBeVisible();
  const sitesWorkspace = page.locator('[data-portal-home="sites-workspace"]');
  await expect(sitesWorkspace.getByText(/^2 (?:Needs attention|需要关注)$/i)).toBeVisible();
  await expect(sitesWorkspace.getByText(/^Needs attention$|^需要关注$/i)).toHaveCount(2);

  await expect(page.locator('a[href="/portal/sites/site_attention"]').first()).toBeVisible();
  await page.goto('/portal/sites/site_attention');
  await expect(page).toHaveURL(/\/portal\/sites\/site_attention$/);
  await expect(page.getByRole('heading', { level: 1, name: /attention site/i })).toBeVisible();

  await page.goto('/portal/usage');
  await expect(page.getByRole('heading', { level: 1, name: /^Usage$|^用量$/i })).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: /This period|本期用量/i })).toBeVisible();
  await expect(page.getByText(/^612$|^612 点$/i).first()).toBeVisible();
  const usageViewTabs = page.locator('[data-portal-usage="view-tabs"]');
  await expect(usageViewTabs.getByRole('tab')).toHaveCount(2);
  await expect(usageViewTabs.getByRole('tab', { name: /Usage details|用量明细/i })).toHaveCount(0);
  await expect(page.getByText(/^Generated At$|^生成时间$/i)).toHaveCount(0);
  await expect(page.getByText(/Apr 1[^\n]*Apr 30|4(?:月|\/)1(?:日)?[^\n]*4(?:月|\/)30日?/i).first()).toBeVisible();
  await expect(page.getByText(/Ends .*2026.*Apr 30|截止 .*2026.*4(?:月|\/)30日?/i).first()).toBeVisible();
  await expect(page.getByText(/Updated .*Apr 7|更新于 .*4(?:月|\/)7日?/i).first()).toBeVisible();
  await expect(usageViewTabs.getByRole('tab', { name: /^Trend$|^趋势$/i })).toHaveAttribute('aria-selected', 'true');
  const trendPanel = page.locator('[data-portal-usage="primary-trend"]');
  await expect(trendPanel.getByRole('tab', { name: /24 hours|最近 24 小时/i })).toHaveAttribute('aria-selected', 'true');
  await expect(trendPanel.locator('[data-trend-window="24h"]')).toHaveAttribute('data-trend-points', '24');
  await expect(trendPanel.getByText(/24 points used|共使用 24 点/i)).toBeVisible();
  for (const range of [
    { name: /1 hour|最近 1 小时/i, value: '1h', points: '12' },
    { name: /7 days|最近 7 天/i, value: '7d', points: '7' },
    { name: /30 days|最近 30 天/i, value: '30d', points: '30' },
  ]) {
    await trendPanel.getByRole('tab', { name: range.name }).click();
    await expect(trendPanel.locator(`[data-trend-window="${range.value}"]`)).toHaveAttribute('data-trend-points', range.points);
  }
  await usageViewTabs.getByRole('tab', { name: /Point records|点数记录/i }).click();
  await expect(page).toHaveURL(/\/portal\/usage\?view=records$/);
  await expect(page.getByRole('heading', { level: 2, name: /^Point records$|^点数记录$/i })).toBeVisible();
  await expect(page.locator('main').getByRole('combobox')).toHaveCount(4);
  await expect(page.getByRole('combobox', { name: /Summary interval|汇总粒度/i })).toHaveValue('30m');
  const creditBucketRow = page.getByRole('button', { name: /18.*Content writing|18.*内容生成/i }).first();
  await expect(creditBucketRow).toBeVisible();
  await creditBucketRow.click();
  const creditBucketDialog = page.getByRole('dialog', { name: /Apr 7|4\/7/i });
  await expect(creditBucketDialog).toBeVisible();
  const creditEventRow = creditBucketDialog.getByRole('button', { name: /Content writing|内容生成/i });
  await creditEventRow.click();
  const creditEventDialog = page.getByRole('dialog', { name: /Content writing|内容生成/i });
  await expect(creditEventDialog.getByText(/Point breakdown|点数构成/i)).toBeVisible();
  await creditEventDialog.getByText(/Support information|支持信息/i).click();
  await expect(creditEventDialog.getByText(/run_portal_001/i)).toBeVisible();
  await creditEventDialog.getByRole('button', { name: /Close|关闭/i }).click();
  await page.reload();
  const reloadedRecordsTab = page.locator('[data-portal-usage="view-tabs"]').getByRole('tab', { name: /Point records|点数记录/i });
  await expect(reloadedRecordsTab).toHaveAttribute('aria-selected', 'true');
  await page.locator('[data-portal-usage="view-tabs"]').getByRole('tab', { name: /^Trend$|^趋势$/i }).click();
  await expect(page).toHaveURL(/\/portal\/usage$/);
  await expect(page.locator('[data-portal-usage="view-tabs"]').getByRole('tab', { name: /^Trend$|^趋势$/i })).toHaveAttribute('aria-selected', 'true');
  await page.goto('/portal/usage?view=details');
  await expect(page).toHaveURL(/\/portal\/usage$/);

  await page.goto('/portal/billing');
  await expect(page.getByRole('heading', { level: 1, name: /Package|套餐/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Submit ticket|提交工单|提交工單/i })).toHaveCount(0);
  await page.getByRole('button', { name: /Upgrade package|升级套餐/i }).click();
  const packageDialog = page.getByRole('dialog', { name: /Choose a package|选择套餐/i });
  await expect(packageDialog).toBeVisible();
  const packageConfirmButton = packageDialog.getByRole('button', { name: /^Select package$|^选择套餐$/i });
  await expect(packageConfirmButton).toBeInViewport();
  await expect(packageDialog.getByRole('heading', { name: /Compare package rights|套餐权益对比/i })).toBeVisible();
  await expect(packageDialog.locator('[data-comparison-state="unconfigured"]')).toContainText(/To confirm|待确认/i);
  await expect(packageDialog.getByText(/published package does not currently define|已发布套餐尚未定义/i)).toBeVisible();
  await expect(packageDialog.getByRole('radio', { name: /Plus/i })).toBeDisabled();
  await expect(packageDialog.getByRole('radio', { name: /Pro/i })).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(page.getByText(/^Payment orders$|^支付订单$/i)).toBeVisible();
  await expect(page.getByRole('tab', { name: /Pending|待支付/i })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('link', { name: /Continue payment|继续支付/i })).toBeVisible();
  await expect(page.getByText(/Complete payment before|前完成支付/i).first()).toBeVisible();
  const paymentPopupPromise = page.waitForEvent('popup');
  await page.getByRole('button', { name: /Buy credits|购买积分/i }).click();
  const creditDialog = page.getByRole('dialog', { name: /Credit packs|积分包/i });
  await expect(creditDialog.getByText(/Valid for 180 days|支付后 180 天内有效/i).first()).toBeVisible();
  await creditDialog.getByRole('radio', { name: /Small credit pack|小积分包/i }).click();
  await creditDialog.getByRole('button', { name: /Buy credits|购买积分/i }).click();
  const paymentPopup = await paymentPopupPromise;
  await paymentPopup.waitForURL('https://pay.example.com/pay_credit_pack_new_tab');
  await expect(page.getByText(/Alipay opened in a new tab|支付宝已在新标签页打开/i)).toBeVisible();
  await paymentPopup.close();
  const creditPackOrder = page.locator('[data-payment-order-id="pay_pending_visible"]');
  await expect(creditPackOrder.getByText(/Small credit pack|小积分包|小積分包/i)).toBeVisible();
  await expect(creditPackOrder.getByText(/Waiting for payment confirmation|等待支付确认/i)).toHaveCount(1);
  await creditPackOrder.getByRole('button', { name: /Cancel|取消订单/i }).click();
  await creditPackOrder.getByRole('button', { name: /Confirm cancel|确认取消/i }).click();
  await expect(page.locator('[data-payment-order-id="pay_pending_visible"]')).toHaveCount(0);
  await page.getByRole('tab', { name: /Closed|已关闭/i }).click();
  await expect(page.locator('[data-payment-order-id="pay_pending_visible"]')).toContainText(/Canceled|已取消/i);
  await expect(page.getByText(/Medium credit pack|中积分包|中積分包/i)).toBeVisible();
});

test('Alipay return polls from pending to paid and shows reconciled credit details', async ({
  page,
}) => {
  await installPortalMocks(page, { paymentReturnFlow: true });

  await page.goto(
    '/portal/billing?payment_return=alipay&out_trade_no=pay_return_polling'
  );

  const notice = page.locator('[data-ui="payment-return-notice"]');
  await expect(notice.getByText(/^(Payment confirmed|支付已确认)$/i)).toBeVisible({ timeout: 10_000 });
  await expect(notice.locator('[data-payment-return-metric="credited"]')).toContainText('10,000');
  await expect(notice.locator('[data-payment-return-metric="total-available"]')).toContainText('12,419');
  await expect(notice.locator('[data-payment-return-metric="next-expiry"]')).toContainText('2027');
  await expect(page).toHaveURL('/portal/billing');
});

test('legacy portal sites route redirects to the merged service workspace', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/sites');
  await expect(page).toHaveURL(/\/portal#sites$/);
  await expect(page.getByRole('heading', { level: 1, name: /my service|我的服务|服務/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Search site name or URL|搜索站点名称或网址/i)).toBeVisible();
  await expect(page.getByText(/Current site|当前站点|目前站點/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Select$|^选择$|^選擇$/i })).toHaveCount(0);
  await expect(page.locator('a[href="/portal/sites/site_attention"]').first()).toBeVisible();
  await expect(page.locator('section').first().locator('.btn.btn-primary')).toHaveCount(0);
});

test('portal account page hides internal identifiers and duplicate summary metrics', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/account');
  await expect(page.getByRole('heading', { level: 1, name: /Account|账号|帳號/i })).toBeVisible();
  await expect(page.locator('[data-portal-account="contact-info"]')).toHaveCount(1);
  await expect(page.locator('[data-portal-account="support-details"]')).toHaveCount(0);
  await expect(page.getByText(/portal-demo@example\.com/i).first()).toBeVisible();
  await expect(page.getByText(/Primary login method|主要登录方式/i)).toHaveCount(0);
  await page.getByRole('button', { name: /Need to change contact|需要修改联系方式/i }).click();
  await expect(page.locator('[data-portal-account="email-change-dialog"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByText(/prn_8d95fab64fa7487bb31cd81c3adac4a8/i)).toHaveCount(0);
  await expect(page.getByText(/acct_portal/i)).not.toBeVisible();
});

test('legacy monitoring redirects to site status while audit stays a support deep link', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/monitoring?site=site_attention');

  await expect(page).toHaveURL(/\/portal\/sites\/site_attention#service-status$/);
  await expect(page.getByText(/Service status|服务状态|服務狀態/i).first()).toBeVisible();
  await expect(page.getByText(/suggestion only|no direct wordpress write|diagnostic advisor/i)).toHaveCount(0);

  await page.goto('/portal/audit');
  await expect(page.locator('[data-portal-support-deeplink="audit"]')).toHaveCount(1);
  await expect(page.getByRole('heading', { level: 1, name: /Recent activity|最近活动|最近活動/i })).toBeVisible();
  await expect(page.getByRole('article')).toHaveCount(10);
  await page.getByRole('button', { name: /Load more activity|加载更多活动|載入更多活動/i }).click();
  await expect(page.getByRole('article')).toHaveCount(12);
  await page.getByText(/Support information|支持信息|支援資訊/i).first().click();
  await expect(page.getByText('trace_portal_e2e')).toBeVisible();
});

test('portal site record focuses on address, status, and support actions', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/sites/site_attention');
  await expect(page.getByText(/Site record|站点记录|站點記錄/i).first()).toBeVisible();
  await expect(page.getByText(/Site address|站点地址|站點地址/i).first()).toBeVisible();
  await expect(page.getByText(/Current package|当前套餐|目前方案/i)).toHaveCount(0);
  await expect(page.getByText(/^Pro$/)).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Preferences|个人偏好|偏好設定/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Audit|审计|稽核/i })).toHaveCount(0);

  await page.goto('/portal/sites/site_clear');
  await expect(page.getByText(/Site address|站点地址|站點地址/i).first()).toBeVisible();
  await expect(page.getByText(/^Growth$/)).toHaveCount(0);
  await expect(page.getByText(/^plan_growth$/)).toHaveCount(0);
  const siteKnowledgePanel = page.locator('[data-portal-site="site-knowledge"]');
  await expect(siteKnowledgePanel.getByRole('heading', { name: /Site knowledge|站点知识/i })).toBeVisible();
  await expect(siteKnowledgePanel.getByText(/^86$/)).toBeVisible();
  await expect(siteKnowledgePanel.getByText(/32 searches|32 次搜索/i)).toBeVisible();
  await expect(siteKnowledgePanel.getByText(/3 could not find|3 次未找到相关内容/i)).toBeVisible();
  await expect(siteKnowledgePanel.getByText(/P95|top1|embedding|vector backend|向量库|分块/i)).toHaveCount(0);
});

test('portal support owns customer feedback and status expectations', async ({ page }) => {
  await installPortalMocks(page);

  await page.goto('/portal/support');
  await expect(page.getByRole('heading', { level: 1, name: /Tickets|工单|工單/i })).toBeVisible();
  await expect(page.locator('[data-portal-support="status-rules"]')).toHaveCount(1);
  await page.locator('[data-portal-support="status-rules"] summary').click();
  await expect(page.getByText(/Open tickets are waiting|待处理工单/i)).toBeVisible();
  await expect(page.getByText(/Close evaluation|关闭评价|關閉評價/i).first()).toBeVisible();
  await expect(page.getByText(/Payment order status looks wrong|支付订单状态看起来不对/i)).toBeVisible();
  await page.getByRole('button', { name: /Submit ticket|提交工单/i }).click();
  await expect(page.locator('[data-portal-support="new-ticket-dialog"]')).toBeVisible();
  await page.keyboard.press('Escape');
});

test('portal point trend shows an explicit empty state instead of a blank chart', async ({ page }) => {
  await installPortalMocks(page, { emptyCreditTrend: true });

  await page.goto('/portal/usage');
  const trendPanel = page.locator('[data-portal-usage="primary-trend"]');
  await expect(trendPanel.getByText(/No point usage in this range|该时间范围内暂无点数使用/i)).toBeVisible();
  await expect(trendPanel.getByRole('img')).toHaveCount(0);
});

test('portal usage and workspace stay usable on mobile viewport', async ({ page }) => {
  await installPortalMocks(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/portal');
  await expect(page.getByRole('heading', { level: 1, name: /my service|我的服务|服務/i })).toBeVisible();
  await expect(page.getByText(/Current package|当前套餐|目前方案/i).first()).toBeVisible();

  await page.goto('/portal/usage');
  await expect(page.getByRole('heading', { level: 1, name: /^Usage$|^用量$/i })).toBeVisible();
  await page.locator('[data-portal-usage="view-tabs"]').getByRole('tab', { name: /Point records|点数记录/i }).click();
  await expect(page.getByRole('heading', { level: 2, name: /^Point records$|^点数记录$/i })).toBeVisible();
});
