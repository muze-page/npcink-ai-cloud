import type { Page, Route } from '@playwright/test';


export const BASE_URL =
  process.env.NPCINK_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.NPCINK_CLOUD_FRONTEND_PORT || '3301'}`;
export const LONG_ACCOUNT_ID = 'acct_mvp_enterprise_primary';
export const LONG_PROVIDER_ID = 'mini-vllm-demo-execution-primary';
export const LONG_PLAN_ID = 'pro';
export const LONG_PLAN_VERSION_ID = 'pro_v1';
export const FREE_PLAN_ID = 'free';
export const FREE_PLAN_VERSION_ID = 'free_v1';

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'ok', data }),
  });
}

export async function installAdminMocks(page: Page) {
  let primaryAccountSubscription = {
    subscription_id: 'sub_mvp',
    status: 'past_due',
    plan_id: 'pro',
    plan_version_id: 'pro_v1',
    plan_kind: 'tier_paid',
    package_alias: 'Pro',
    package_kind: 'tier_package',
    coverage_state: 'uncovered',
    display_package_label: 'Pro',
    current_period_start: '2026-04-01T00:00:00Z',
    current_period_end: '2026-04-12T00:00:00Z',
  };
  let primaryAccountCoverageFollowUp = true;
  let accountItems = [
    {
      account: {
        account_id: LONG_ACCOUNT_ID,
        name: 'MVP Account',
        status: 'active',
        metadata: {
          operator_display_name: 'Npcink AI Demo',
          operator_note: 'Pilot customer. Confirm package before public release.',
        },
        created_at: '2026-02-01T00:00:00Z',
      },
      member_count: 1,
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: 'pro',
      package_alias: 'Pro',
      plan_kind: 'tier_paid',
      display_package_label: 'Pro',
      package_kind: 'tier_package',
      coverage_state: 'uncovered',
      primary_subscription_id: 'sub_mvp',
      coverage_follow_up_required: true,
      nearest_expiry_at: '2026-04-12T00:00:00Z',
    },
    {
      account: {
        account_id: 'acct_free_primary',
        name: 'Free Account',
        status: 'active',
        created_at: '2026-03-01T00:00:00Z',
      },
      member_count: 1,
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: FREE_PLAN_ID,
      package_alias: 'Free',
      plan_kind: 'default_free',
      display_package_label: 'Free',
      package_kind: 'formal_free',
      coverage_state: 'covered',
      primary_subscription_id: 'sub_free_primary',
      coverage_follow_up_required: false,
      nearest_expiry_at: '2026-05-01T00:00:00Z',
    },
    {
      account: {
        account_id: 'acct_uncovered',
        name: 'Uncovered Account',
        status: 'active',
        created_at: '2026-03-05T00:00:00Z',
      },
      member_count: 1,
      site_count: 1,
      active_subscription_count: 0,
      top_plan_id: '',
      package_alias: '',
      plan_kind: '',
      display_package_label: 'Uncovered',
      package_kind: 'uncovered',
      coverage_state: 'uncovered',
      primary_subscription_id: '',
      coverage_follow_up_required: true,
      nearest_expiry_at: '',
    },
  ];
  await page.context().addCookies([
    {
      name: 'npcink_admin_session_token',
      value: 'e2e-admin-session',
      url: BASE_URL,
    },
  ]);

  await page.route('**/admin/session', async (route) => {
    await fulfillJson(route, {
      principal_id: 'platform:operator-e2e',
      identity_type: 'platform_admin',
      role: 'platform_admin',
    });
  });

  await page.route('**/api/admin/**', async (route) => {
    const url = new URL(route.request().url());
    const { pathname, searchParams } = url;

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/subscription` && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      const nextPlanId = String(payload.plan_id || primaryAccountSubscription.plan_id);
      const nextPackageAlias = nextPlanId === FREE_PLAN_ID ? 'Free' : 'Pro';
      const nextPlanKind = nextPlanId === FREE_PLAN_ID ? 'default_free' : 'tier_paid';
      const nextPackageKind = nextPlanId === FREE_PLAN_ID ? 'formal_free' : 'tier_package';
      primaryAccountSubscription = {
        ...primaryAccountSubscription,
        subscription_id: String(payload.subscription_id || primaryAccountSubscription.subscription_id),
        plan_id: nextPlanId,
        plan_version_id: String(payload.plan_version_id || primaryAccountSubscription.plan_version_id),
        status: String(payload.status || 'active'),
        plan_kind: nextPlanKind,
        package_alias: nextPackageAlias,
        package_kind: nextPackageKind,
        coverage_state: 'covered',
        display_package_label: nextPackageAlias,
        current_period_start: String(payload.current_period_start_at || primaryAccountSubscription.current_period_start),
        current_period_end: String(payload.current_period_end_at || primaryAccountSubscription.current_period_end),
      };
      primaryAccountCoverageFollowUp = false;
      accountItems = accountItems.map((item) =>
        item.account.account_id === LONG_ACCOUNT_ID
          ? {
              ...item,
              top_plan_id: primaryAccountSubscription.plan_id,
              package_alias: primaryAccountSubscription.package_alias,
              plan_kind: primaryAccountSubscription.plan_kind,
              display_package_label: primaryAccountSubscription.display_package_label,
              package_kind: primaryAccountSubscription.package_kind,
              coverage_state: 'covered',
              primary_subscription_id: primaryAccountSubscription.subscription_id,
              coverage_follow_up_required: false,
            }
          : item
      );
      await fulfillJson(route, {
        account_id: LONG_ACCOUNT_ID,
        subscription_id: primaryAccountSubscription.subscription_id,
        plan_id: primaryAccountSubscription.plan_id,
        plan_version_id: primaryAccountSubscription.plan_version_id,
        status: primaryAccountSubscription.status,
        receipt: {
          event_kind: 'account.subscription.change',
          scope_kind: 'account',
          scope_id: LONG_ACCOUNT_ID,
          outcome: 'succeeded',
          effective_summary: `Customer package changed to ${nextPackageAlias}.`,
        },
      });
      return;
    }

    if (
      pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/credit-ledger/adjustments` &&
      route.request().method() === 'POST'
    ) {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, {
        account_id: LONG_ACCOUNT_ID,
        entry: {
          event_type: String(payload.event_type || 'grant'),
          credit_delta: Number(payload.credit_delta || 0),
          reason: String(payload.reason || ''),
          note: String(payload.note || ''),
        },
        receipt: {
          event_kind: 'account.credit.adjustment',
          scope_kind: 'account',
          scope_id: LONG_ACCOUNT_ID,
          outcome: 'succeeded',
          effective_summary: `Credit adjustment ${Number(payload.credit_delta || 0)} recorded.`,
        },
      });
      return;
    }

    if (pathname === '/api/admin/subscriptions/sub_mvp/topup' && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, {
        subscription: primaryAccountSubscription,
        topup: {
          topup_id: 'topup_e2e_small',
          pack_id: 'pack_small',
          runs_increment: Number(payload.runs_increment || 0),
          tokens_increment: Number(payload.tokens_increment || 0),
          cost_increment: Number(payload.cost_increment || 0),
          reason: String(payload.reason || ''),
        },
        topup_summary: {
          current_period_count: 1,
          current_period_totals: {
            runs: Number(payload.runs_increment || 0),
            tokens: Number(payload.tokens_increment || 0),
            cost: Number(payload.cost_increment || 0),
          },
        },
      });
      return;
    }

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/subscription/suspend`) {
      primaryAccountSubscription = {
        ...primaryAccountSubscription,
        status: 'suspended',
        coverage_state: 'uncovered',
      };
      primaryAccountCoverageFollowUp = true;
      await fulfillJson(route, {
        account_id: LONG_ACCOUNT_ID,
        subscription_id: primaryAccountSubscription.subscription_id,
        status: 'suspended',
      });
      return;
    }

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/subscription/cancel`) {
      primaryAccountSubscription = {
        ...primaryAccountSubscription,
        status: 'canceled',
        coverage_state: 'uncovered',
      };
      primaryAccountCoverageFollowUp = true;
      await fulfillJson(route, {
        account_id: LONG_ACCOUNT_ID,
        subscription_id: primaryAccountSubscription.subscription_id,
        status: 'canceled',
      });
      return;
    }

    if (pathname === '/api/admin/audit-events/summary') {
      await fulfillJson(route, {
        generated_at: '2026-04-08T10:00:00Z',
        totals: {
          events: 4,
          succeeded: 3,
          error: 1,
        },
        groups: [
          {
            event_kind: searchParams.get('site_id') ? 'subscription.bind' : 'provider_connection.sync',
            outcome: 'succeeded',
            count: 2,
            first_seen_at: '2026-04-08T08:30:00Z',
            last_seen_at: '2026-04-08T09:45:00Z',
          },
          {
            event_kind: 'provider_connection.sync',
            outcome: 'error',
            count: 1,
            first_seen_at: '2026-04-08T07:15:00Z',
            last_seen_at: '2026-04-08T07:15:00Z',
          },
        ],
      });
      return;
    }

    if (pathname === '/api/admin/overview') {
      await fulfillJson(route, {
        generated_at: '2026-04-06T10:00:00Z',
        counts: {
          accounts_total: 1,
          memberships_active: 3,
          sites_total: 1,
          sites_active: 1,
          subscriptions_total: 1,
          subscriptions_active: 1,
          site_keys_active: 1,
        },
        expiring_subscriptions: {
          within_7_days: 1,
          within_30_days: 1,
          items: [
            {
              subscription: {
                subscription_id: 'sub_mvp',
                status: 'past_due',
                current_period_end_at: '2026-04-12T00:00:00Z',
              },
              account: { account_id: LONG_ACCOUNT_ID },
              site: { site_id: 'site_mvp' },
              expiry: { current_period_end_at: '2026-04-12T00:00:00Z', days_until_end: 6 },
            },
          ],
        },
        attention_subscriptions: [
          {
            subscription: { subscription_id: 'sub_mvp', status: 'past_due' },
            account: { account_id: LONG_ACCOUNT_ID },
            site: { site_id: 'site_mvp' },
            reason: 'Billing follow-up is active.',
          },
        ],
        runtime_diagnostics: {
          queue: { queued_runs: 2, running_runs: 1 },
          callback: { failed: 0, pending: 1 },
          guard: { recent_events: 1 },
        },
        runtime_operator_explanations: [
          {
            state: 'policy_gated',
            explain_text: 'Recent guard events suggest a policy or throttle gate is already affecting runtime behavior.',
            next_step_kind: 'subscription',
            next_step_ref: 'sub_mvp',
          },
        ],
        recent_usage: {
          window_days: 7,
          totals: { runs: 21, provider_calls: 21, tokens_total: 32000, cost: 18.42 },
        },
        runtime_telemetry: {
          generated_at: '2026-04-08T10:00:00Z',
          filters: { site_id: '', recent_minutes: 1440, limit: 10 },
          totals: {
            runs: 6,
            provider_calls: 5,
            usage_meter_events: 6,
            provider_call_run_coverage_rate: 0.8333,
            metered_run_coverage_rate: 1,
          },
          alert_summary: {
            status: 'warning',
            summary: 'Runtime telemetry has coverage gaps to review before traffic expands.',
            next_action: 'inspect_provider_call_recording_for_hosted_profiles',
            href: '/admin/troubleshooting',
            alert_count: 1,
            alerts: [
              {
                code: 'hosted_model.provider_call_gap',
                severity: 'warning',
                title: 'Provider call coverage gap',
                summary: 'Some runtime runs do not have matching provider call telemetry.',
                count: 1,
                capabilities: ['knowledge'],
                suggested_action: 'inspect_provider_call_recording_for_hosted_profiles',
                href: '/admin/troubleshooting',
              },
            ],
            daily_digest: {
              runs: 6,
              provider_calls: 5,
              meter_events: 6,
              metered_run_coverage_rate: 1,
              provider_call_run_coverage_rate: 0.8333,
              unmetered_run_count: 0,
              runs_without_provider_call_count: 1,
            },
            boundary: {
              surface: 'internal_admin_summary',
              cloud_role: 'hosted_runtime_detail',
              local_control_plane: 'wordpress_plugin',
              direct_wordpress_write: false,
              contains_prompt_or_result_payloads: false,
            },
          },
          boundary: {
            surface: 'internal_operator_diagnostics',
            cloud_role: 'hosted_runtime_detail',
            local_control_plane: 'wordpress_plugin',
            direct_wordpress_write: false,
            contains_prompt_or_result_payloads: false,
          },
        },
        plan_distribution: [{ plan_id: 'pro', count: 1 }],
        recent_audit_summary: { items: [] },
      });
      return;
    }

    if (pathname === '/api/admin/commercial-shadow-pricing/summary') {
      await fulfillJson(route, {
        window: { start_at: '2026-03-01T00:00:00Z', end_at: '2026-03-31T00:00:00Z', window_days: 30 },
        totals: {
          runs: 21,
          provider_calls: 21,
          tokens_total: 32000,
          provider_cost: 18.42,
          shadow_revenue: 29.99,
          margin_delta: 11.57,
        },
        top_abilities: [],
        top_families: [],
        attention_items: [],
      });
      return;
    }

    if (pathname === '/api/admin/runtime-telemetry') {
      await fulfillJson(route, {
        generated_at: '2026-04-08T10:00:00Z',
        filters: {
          site_id: searchParams.get('site_id') || '',
          recent_minutes: Number(searchParams.get('recent_minutes') || 1440),
          limit: Number(searchParams.get('limit') || 25),
        },
        totals: {
          runs: 6,
          provider_calls: 5,
          usage_meter_events: 6,
          provider_call_run_coverage_rate: 0.8333,
          metered_run_coverage_rate: 1,
        },
        capability_groups: [
          {
            group_kind: 'ability_family',
            group_id: 'text',
            runs_total: 4,
            succeeded: 4,
            failed: 0,
            queued: 0,
            running: 0,
            canceled: 0,
            provider_calls: 4,
            provider_errors: 0,
            tokens_in: 3200,
            tokens_out: 1400,
            tokens_total: 4600,
            cost: 0.021,
            meter_events: 4,
            meter_totals: { runs: 4, tokens: 4600, cost: 0.021 },
            avg_latency_ms: 820,
            provider_error_rate: 0,
            provider_call_run_coverage_rate: 1,
            metered_run_coverage_rate: 1,
            profile_ids: ['free-gpt55-general'],
            execution_kinds: ['provider_hosted'],
            provider_ids: ['newapi'],
            model_ids: ['gpt-5.5'],
            data_classifications: ['text'],
          },
          {
            group_kind: 'ability_family',
            group_id: 'knowledge',
            runs_total: 2,
            succeeded: 2,
            failed: 0,
            queued: 0,
            running: 0,
            canceled: 0,
            provider_calls: 1,
            provider_errors: 0,
            tokens_in: 0,
            tokens_out: 0,
            tokens_total: 0,
            cost: 0.004,
            meter_events: 2,
            meter_totals: { runs: 2, embeddings: 1, cost: 0.004 },
            avg_latency_ms: 210,
            provider_error_rate: 0,
            provider_call_run_coverage_rate: 0.5,
            metered_run_coverage_rate: 1,
            profile_ids: ['site-knowledge-embedding'],
            execution_kinds: ['provider_hosted'],
            provider_ids: ['newapi'],
            model_ids: ['text-embedding-gpt-5.5'],
            data_classifications: ['vector'],
          },
        ],
        profile_groups: [
          {
            group_kind: 'profile',
            group_id: 'free-gpt55-general',
            runs_total: 4,
            succeeded: 4,
            failed: 0,
            queued: 0,
            running: 0,
            canceled: 0,
            provider_calls: 4,
            provider_errors: 0,
            tokens_in: 3200,
            tokens_out: 1400,
            tokens_total: 4600,
            cost: 0.021,
            meter_events: 4,
            meter_totals: { runs: 4, tokens: 4600, cost: 0.021 },
            avg_latency_ms: 820,
            provider_error_rate: 0,
            provider_call_run_coverage_rate: 1,
            metered_run_coverage_rate: 1,
            profile_ids: ['free-gpt55-general'],
            execution_kinds: ['provider_hosted'],
            provider_ids: ['newapi'],
            model_ids: ['gpt-5.5'],
            data_classifications: ['text'],
          },
        ],
        execution_kind_groups: [],
        provider_model_groups: [
          {
            group_kind: 'provider_model',
            group_id: 'newapi:gpt-5.5',
            runs_total: 4,
            succeeded: 4,
            failed: 0,
            queued: 0,
            running: 0,
            canceled: 0,
            provider_calls: 4,
            provider_errors: 0,
            tokens_in: 3200,
            tokens_out: 1400,
            tokens_total: 4600,
            cost: 0.021,
            meter_events: 4,
            meter_totals: { runs: 4, tokens: 4600, cost: 0.021 },
            avg_latency_ms: 820,
            provider_error_rate: 0,
            provider_call_run_coverage_rate: 1,
            metered_run_coverage_rate: 1,
            profile_ids: ['free-gpt55-general'],
            execution_kinds: ['provider_hosted'],
            provider_ids: ['newapi'],
            model_ids: ['gpt-5.5'],
            data_classifications: ['text'],
          },
        ],
        governance_gaps: {
          unmetered_capabilities: [],
          missing_provider_call_capabilities: ['knowledge'],
          unmetered_run_count: 0,
          runs_without_provider_call_count: 1,
          review_guidance: 'Inspect capabilities below full metering coverage before enabling new runtime providers at higher traffic.',
        },
        alert_summary: {
          status: 'warning',
          summary: 'Runtime telemetry has coverage gaps to review before traffic expands.',
          next_action: 'inspect_provider_call_recording_for_hosted_profiles',
          href: '/admin/troubleshooting',
          alert_count: 1,
          alerts: [
            {
              code: 'hosted_model.provider_call_gap',
              severity: 'warning',
              title: 'Provider call coverage gap',
              summary: 'Some runtime runs do not have matching provider call telemetry.',
              count: 1,
              capabilities: ['knowledge'],
              suggested_action: 'inspect_provider_call_recording_for_hosted_profiles',
              href: '/admin/troubleshooting',
            },
          ],
          daily_digest: {
            runs: 6,
            provider_calls: 5,
            meter_events: 6,
            metered_run_coverage_rate: 1,
            provider_call_run_coverage_rate: 0.8333,
            unmetered_run_count: 0,
            runs_without_provider_call_count: 1,
          },
          boundary: {
            surface: 'internal_admin_summary',
            cloud_role: 'hosted_runtime_detail',
            local_control_plane: 'wordpress_plugin',
            direct_wordpress_write: false,
            contains_prompt_or_result_payloads: false,
          },
        },
        boundary: {
          surface: 'internal_admin',
          cloud_role: 'hosted_runtime_detail',
          local_control_plane: 'wordpress_plugin',
          direct_wordpress_write: false,
          contains_prompt_or_result_payloads: false,
        },
      });
      return;
    }

    if (pathname === '/api/admin/coverage-work-queue') {
      const items = accountItems.map((item) => {
        const isPrimary = item.account.account_id === LONG_ACCOUNT_ID;
        const hasSubscription = Boolean(item.primary_subscription_id);
        const isUncovered = !hasSubscription && item.coverage_state === 'uncovered' && item.site_count > 0;
        const reasonCode = isUncovered
          ? 'missing_package_coverage'
          : isPrimary
            ? 'subscription_lifecycle_risk'
            : 'service_coverage_aligned';
        const severity = isUncovered || isPrimary ? 'error' : 'ok';
        const subscriptionId = item.primary_subscription_id || '';
        return {
          account: item.account,
          primary_subscription: subscriptionId
            ? {
                subscription_id: subscriptionId,
                status: isPrimary ? primaryAccountSubscription.status : 'active',
                current_period_end_at: item.nearest_expiry_at || '2026-05-01T00:00:00Z',
              }
            : null,
          package: {
            display_package_label: item.display_package_label,
            package_kind: item.package_kind,
            coverage_state: item.coverage_state,
          },
          severity,
          priority: severity === 'error' ? 0 : 90,
          reason_code: reasonCode,
          reason_label:
            reasonCode === 'missing_package_coverage'
              ? 'Customer has sites but no active package coverage.'
              : reasonCode === 'subscription_lifecycle_risk'
                ? 'Subscription status can block service continuity.'
                : 'Package, subscription, site, key, and billing evidence are aligned.',
          recommended_action:
            reasonCode === 'missing_package_coverage'
              ? 'change_customer_package'
              : reasonCode === 'subscription_lifecycle_risk'
                ? 'repair_subscription_lifecycle'
                : 'inspect_when_needed',
          action_label:
            reasonCode === 'missing_package_coverage'
              ? 'Open package actions'
              : reasonCode === 'subscription_lifecycle_risk'
                ? 'Inspect subscription'
                : 'Open customer',
          action_href:
            reasonCode === 'subscription_lifecycle_risk' && subscriptionId
              ? `/admin/subscriptions/${subscriptionId}`
              : `/admin/accounts/${item.account.account_id}#coverage-actions`,
          evidence: {
            site_count: item.site_count,
            active_site_count: item.site_count,
            active_key_site_count: isUncovered ? 0 : item.site_count,
            missing_key_site_count: isUncovered ? item.site_count : 0,
            subscription_status: isPrimary ? primaryAccountSubscription.status : subscriptionId ? 'active' : 'missing',
            current_period_end_at: item.nearest_expiry_at || '',
            days_until_end: isPrimary ? 6 : null,
            billing_snapshot_status: {
              status: isUncovered ? 'missing' : 'fresh',
              summary: isUncovered
                ? 'Current-period billing snapshots are still missing for at least one covered site.'
                : 'Current-period billing snapshots are fresh for every covered site.',
              fresh_site_count: isUncovered ? 0 : item.site_count,
              stale_site_count: 0,
              missing_site_count: isUncovered ? item.site_count : 0,
            },
          },
        };
      });
      await fulfillJson(route, {
        generated_at: '2026-04-06T10:00:00Z',
        summary: {
          total: items.length,
          visible: items.length,
          needs_action: items.filter((item) => item.severity === 'error' || item.severity === 'warning').length,
          error: items.filter((item) => item.severity === 'error').length,
          warning: items.filter((item) => item.severity === 'warning').length,
          ok: items.filter((item) => item.severity === 'ok').length,
          inactive: 0,
          reason_counts: items.reduce<Record<string, number>>((counts, item) => {
            counts[item.reason_code] = (counts[item.reason_code] || 0) + 1;
            return counts;
          }, {}),
        },
        items,
      });
      return;
    }

    if (pathname === '/api/admin/subscriptions') {
      await fulfillJson(route, {
        total: 1,
        items: [
          {
            subscription: {
              subscription_id: 'sub_mvp',
              account_id: LONG_ACCOUNT_ID,
              status: 'past_due',
              plan_id: 'pro',
              plan_version_id: 'pro_v1',
              current_period_start_at: '2026-04-01T00:00:00Z',
              current_period_end_at: '2026-04-12T00:00:00Z',
            },
            account: { account_id: LONG_ACCOUNT_ID, name: 'MVP Account' },
            covered_sites: [{ site_id: 'site_mvp', name: 'MVP Site' }],
            coverage: { site_count: 1, package_alias: 'Pro' },
            latest_billing_snapshots: [{ snapshot_id: 'snap_mvp', totals: { cost: 18.42 } }],
            billing_snapshot_status: {
              status: 'fresh',
              summary: 'Current-period billing snapshots are fresh for every covered site.',
              fresh_site_count: 1,
              stale_site_count: 0,
              missing_site_count: 0,
            },
          },
        ],
      });
      return;
    }

    if (pathname === '/api/admin/subscriptions/sub_mvp') {
      await fulfillJson(route, {
        subscription: {
          subscription_id: 'sub_mvp',
          account_id: LONG_ACCOUNT_ID,
          status: 'past_due',
          plan_id: 'pro',
          plan_version_id: 'pro_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        account: { account_id: LONG_ACCOUNT_ID, name: 'MVP Account', status: 'active' },
        covered_sites: [{ site_id: 'site_mvp', name: 'MVP Site', status: 'active' }],
        plan: { plan_id: 'pro', display_name: 'Pro' },
        plan_version: { plan_version_id: 'pro_v1' },
        commercial_policy: { subscription: { grace_period_days: 3 } },
        budget_headroom: {
          base_budget: { runs: 1000, tokens: 500000, cost: 250 },
          current_period_topup_delta: { runs: 35000, tokens: 7000000, cost: 349 },
          effective_budget: { runs: 36000, tokens: 7500000, cost: 599 },
        },
        budget_state: {
          runs: { current_total: 21, limit: 36000 },
          tokens: { current_total: 32000, limit: 7500000 },
          cost: { current_total: 18.42, limit: 599 },
        },
        billing_snapshot_status: {
          status: 'fresh',
          summary: 'Current-period billing snapshots are fresh for every covered site.',
          site_count: 1,
          fresh_site_count: 1,
          stale_site_count: 0,
          missing_site_count: 0,
          next_action: null,
        },
        subscription_grace: { subscription_status: 'past_due', active: true, grace_until_at: '2026-04-15T00:00:00Z' },
        usage_totals: { runs: 21, tokens: 32000, cost: 18.42 },
        related_surfaces: {
          site_href: '/admin/sites/site_mvp',
          account_href: `/admin/accounts/${LONG_ACCOUNT_ID}`,
          audit_href: `/api/admin/audit-events?site_id=site_mvp&account_id=${LONG_ACCOUNT_ID}&limit=20`,
        },
        commercial_follow_up: {
          lifecycle_posture: 'Read current status and grace posture first.',
          snapshot_reconciliation_summary: 'Use site detail and filtered audit evidence to confirm whether snapshot posture and impact are aligned.',
          next_operator_follow_up: 'Open site detail for runtime and entitlement impact.',
        },
        topup_summary: {
          count: 2,
          current_period_count: 1,
          latest: {
            applied_at: '2026-04-08T09:30:00Z',
            pack_id: 'pack_medium',
            pack_label: 'Medium pack',
            points_label: '35,000 points equivalent',
            reason: 'workflow_spike_buffer',
          },
          current_period_totals: {
            runs: 35000,
            tokens: 7000000,
            cost: 349,
          },
        },
      });
      return;
    }

    if (pathname === '/api/admin/subscriptions/sub_mvp/billing-snapshots/rebuild' && route.request().method() === 'POST') {
      await fulfillJson(route, {
        subscription: {
          subscription_id: 'sub_mvp',
          account_id: LONG_ACCOUNT_ID,
          status: 'past_due',
          plan_id: 'pro',
          plan_version_id: 'pro_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        billing_snapshot_refresh: {
          status: 'refreshed',
          summary: 'Current-period billing snapshots were rebuilt for every covered site.',
          site_count: 1,
          snapshots: [
            {
              snapshot_id: 'snap_mvp_rebuilt',
              site_id: 'site_mvp',
              subscription_id: 'sub_mvp',
              totals: { cost: 18.42 },
            },
          ],
        },
        billing_snapshot_status: {
          status: 'fresh',
          summary: 'Current-period billing snapshots are fresh for every covered site.',
          site_count: 1,
          fresh_site_count: 1,
          stale_site_count: 0,
          missing_site_count: 0,
          next_action: null,
        },
        receipt: {
          event_kind: 'subscription.billing_snapshot.rebuild',
          scope_kind: 'subscription',
          scope_id: 'sub_mvp',
          outcome: 'succeeded',
          effective_summary: 'Billing snapshots for subscription sub_mvp were rebuilt from usage records.',
          audit_filters: {
            event_kind: 'subscription.billing_snapshot.rebuild',
            outcome: 'succeeded',
          },
        },
      });
      return;
    }

    if (pathname === '/api/admin/sites') {
      await fulfillJson(route, {
        total: 1,
        items: [
          {
            site: {
              site_id: 'site_mvp',
              account_id: LONG_ACCOUNT_ID,
              name: 'MVP Site',
              status: 'active',
              created_at: '2026-02-01T00:00:00Z',
            },
            site_keys: [{ site_key_id: 'key_1', status: 'active' }],
            memberships: [
              { member_ref: 'user:admin@example.com', identity_type: 'user', role: 'user', status: 'active' },
            ],
            subscription: {
              subscription_id: 'sub_mvp',
              status: 'past_due',
              plan_id: 'pro',
              current_period_start_at: '2026-04-01T00:00:00Z',
              current_period_end_at: '2026-04-12T00:00:00Z',
            },
            usage_meter: {
              totals: { runs: 21, tokens_total: 32000, cost: 18.42 },
            },
            runtime_diagnostics: {
              queue: { queued_runs: 1, running_runs: 1 },
              callback: { failed: 0, pending: 1 },
            },
          },
        ],
      });
      return;
    }

    if (pathname === '/api/admin/sites/site_mvp') {
      await fulfillJson(route, {
        site: {
          site_id: 'site_mvp',
          account_id: LONG_ACCOUNT_ID,
          name: 'MVP Site',
          status: 'active',
          created_at: '2026-02-01T00:00:00Z',
        },
        memberships: [{ member_ref: 'user:admin@example.com', identity_type: 'user', role: 'user', status: 'active' }],
        subscription: {
          subscription_id: 'sub_mvp',
          status: 'past_due',
          plan_id: 'pro',
          plan_version_id: 'pro_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        usage_meter: {
          totals: { runs: 21, tokens_total: 32000, cost: 18.42 },
        },
        billing_reconciliation: { site_id: 'site_mvp', in_sync: true, delta_cost: 0 },
        runtime_diagnostics: { queue: { queued_runs: 1, running_runs: 1 }, callback: { failed: 0, pending: 1 } },
        runtime_operator_explanations: [
          {
            state: 'queued',
            explain_text: 'Queued or backlogged runs are accumulating.',
            next_step_kind: 'site',
            next_step_ref: 'site_mvp',
          },
        ],
        related_surfaces: {
          account_href: `/admin/accounts/${LONG_ACCOUNT_ID}`,
          subscription_href: '/admin/subscriptions/sub_mvp',
          audit_href: '/api/admin/audit-events?site_id=site_mvp&limit=20',
        },
        commercial_follow_up: {
          entitlement_summary: 'Use the linked plan and version snapshot as the current commercial entitlement boundary for this site.',
          budget_headroom_summary: 'Budget headroom should be read before widening runtime troubleshooting.',
          runtime_gating_summary: 'Confirm whether subscription state or downgrade policy is constraining this site.',
          next_operator_follow_up: 'Open the current customer subscription when commercial coverage is the blocker.',
        },
        site_keys: [{ site_key_id: 'key_1', status: 'active' }],
      });
      return;
    }

    if (pathname === '/api/admin/accounts') {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON() as Record<string, unknown>;
        const accountId = String(payload.account_id || 'acct_new_customer_free');
        const name = String(payload.name || 'New Customer');
        const metadata = (payload.metadata || {}) as Record<string, unknown>;
        const bindDefaultFree = Boolean(payload.bind_default_free);
        const nextAccountItem = {
            account: {
              account_id: accountId,
              name,
              status: String(payload.status || 'active'),
              metadata,
              created_at: '2026-04-10T00:00:00Z',
            },
            member_count: 0,
            site_count: 0,
            active_subscription_count: bindDefaultFree ? 1 : 0,
            top_plan_id: bindDefaultFree ? FREE_PLAN_ID : '',
            package_alias: bindDefaultFree ? 'Free' : '',
            plan_kind: bindDefaultFree ? 'default_free' : '',
            display_package_label: bindDefaultFree ? 'Free' : 'Uncovered',
            package_kind: bindDefaultFree ? 'formal_free' : 'uncovered',
            coverage_state: bindDefaultFree ? 'covered' : 'uncovered',
            primary_subscription_id: bindDefaultFree ? `sub_${accountId}_free` : '',
            coverage_follow_up_required: false,
            nearest_expiry_at: '',
          };
        accountItems = accountItems.some((item) => item.account.account_id === accountId)
          ? accountItems.map((item) =>
              item.account.account_id === accountId
                ? {
                    ...item,
                    account: {
                      ...item.account,
                      name,
                      status: String(payload.status || item.account.status || 'active'),
                      metadata,
                    },
                  }
                : item
            )
          : [nextAccountItem, ...accountItems];
        await fulfillJson(route, {
          account_id: accountId,
          name,
          status: 'active',
          current_subscription: bindDefaultFree
            ? {
                subscription_id: `sub_${accountId}_free`,
                plan_id: FREE_PLAN_ID,
                plan_version_id: FREE_PLAN_VERSION_ID,
                package_alias: 'Free',
                status: 'active',
              }
            : null,
        });
        return;
      }
      const coverageState = url.searchParams.get('coverage_state');
      const packageKind = url.searchParams.get('package_kind');
      const topPlanId = url.searchParams.get('top_plan_id');
      const filteredItems = accountItems.filter((item) => {
        if (coverageState && item.coverage_state !== coverageState) {
          return false;
        }
        if (packageKind && item.package_kind !== packageKind) {
          return false;
        }
        if (topPlanId && item.top_plan_id !== topPlanId) {
          return false;
        }
        return true;
      });
      await fulfillJson(route, {
        total: filteredItems.length,
        items: filteredItems,
      });
      return;
    }

    if (pathname === '/api/admin/members') {
      await fulfillJson(route, {
        summary: {
          total: 3,
          members_needing_coverage_follow_up: 2,
          never_logged_in_members: 1,
          disabled_mapped_members: 1,
        },
        items: [
          {
            member_ref: 'user:admin@example.com',
            email: 'admin@example.com',
            identity_type: 'user',
            status: 'active',
            invite_state: 'accepted',
            role: 'user',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 1,
            last_login_at: '2026-04-07T00:00:00Z',
            has_coverage_follow_up: true,
            never_logged_in: false,
            disabled_mapped: false,
            primary_account_id: LONG_ACCOUNT_ID,
            primary_follow_up_site_id: 'site_mvp',
            single_covered_subscription_id: '',
            accounts: [
              {
                account_id: LONG_ACCOUNT_ID,
                account_name: 'MVP Account',
                site_count: 1,
                covered_site_count: 0,
                sites_needing_follow_up_count: 1,
                highlight_site_id: 'site_mvp',
                highlight_subscription_id: 'sub_mvp',
              },
            ],
          },
          {
            member_ref: 'user:pending@example.com',
            email: 'pending@example.com',
            identity_type: 'user',
            status: 'pending_invite',
            invite_state: 'pending',
            role: 'user',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 1,
            last_login_at: '',
            has_coverage_follow_up: true,
            never_logged_in: true,
            disabled_mapped: true,
            primary_account_id: LONG_ACCOUNT_ID,
            primary_follow_up_site_id: 'site_mvp',
            single_covered_subscription_id: '',
            accounts: [
              {
                account_id: LONG_ACCOUNT_ID,
                account_name: 'MVP Account',
                site_count: 1,
                covered_site_count: 0,
                sites_needing_follow_up_count: 1,
                highlight_site_id: 'site_mvp',
                highlight_subscription_id: '',
              },
            ],
          },
          {
            member_ref: 'user:covered@example.com',
            email: 'covered@example.com',
            identity_type: 'user',
            status: 'active',
            invite_state: 'accepted',
            role: 'user',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 0,
            last_login_at: '2026-04-08T00:00:00Z',
            has_coverage_follow_up: false,
            never_logged_in: false,
            disabled_mapped: false,
            primary_account_id: 'acct_growth',
            primary_follow_up_site_id: '',
            single_covered_subscription_id: 'sub_growth',
            accounts: [
              {
                account_id: 'acct_growth',
                account_name: 'Growth Account',
                site_count: 1,
                covered_site_count: 1,
                sites_needing_follow_up_count: 0,
                highlight_site_id: '',
                highlight_subscription_id: 'sub_growth',
              },
            ],
          },
        ],
      });
      return;
    }

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}`) {
      const primaryAccount = accountItems.find((item) => item.account.account_id === LONG_ACCOUNT_ID)?.account;
      await fulfillJson(route, {
        account: {
          account_id: LONG_ACCOUNT_ID,
          name: primaryAccount?.name || 'MVP Account',
          status: primaryAccount?.status || 'active',
          metadata: primaryAccount?.metadata || {},
          created_at: primaryAccount?.created_at || '2026-02-01T00:00:00Z',
        },
        memberships: [{ member_ref: 'user:admin@example.com', identity_type: 'user', role: 'user', status: 'active' }],
        sites: [{ site_id: 'site_mvp', name: 'MVP Site', status: 'active' }],
        subscriptions: [primaryAccountSubscription],
        trial_readiness: {
          status: primaryAccountCoverageFollowUp ? 'action_required' : 'ready',
          next_action: primaryAccountCoverageFollowUp ? 'apply_package_coverage' : 'invite_trial_site',
          next_action_label: primaryAccountCoverageFollowUp ? 'Apply package coverage' : 'Invite trial site',
          blocking_codes: primaryAccountCoverageFollowUp ? ['package_coverage'] : [],
          summary: {
            site_count: 1,
            active_site_count: 1,
            active_key_site_count: 1,
            sites_without_active_key: [],
            member_count: 1,
            active_member_count: 1,
            active_or_pending_member_count: 1,
            subscription_status: primaryAccountSubscription.status,
            display_package_label: primaryAccountSubscription.display_package_label,
            package_kind: primaryAccountSubscription.package_kind,
            coverage_state: primaryAccountCoverageFollowUp ? 'uncovered' : 'covered',
          },
          checks: [
            { code: 'account_active', label: 'Customer active', ok: true, detail: 'Customer record is active.' },
            { code: 'site_attached', label: 'Site attached', ok: true, detail: '1 site(s) attached.' },
            { code: 'sites_active', label: 'Sites active', ok: true, detail: 'Every attached site is active.' },
            { code: 'active_api_key', label: 'Cloud API key', ok: true, detail: 'Every attached site has an active Cloud API key.' },
            {
              code: 'package_coverage',
              label: 'Package coverage',
              ok: !primaryAccountCoverageFollowUp,
              detail: primaryAccountCoverageFollowUp
                ? 'Apply Free, Pro, or Agency coverage before inviting this customer.'
                : 'Pro coverage is ready.',
            },
            { code: 'portal_admin', label: 'Portal user', ok: true, detail: '1 active or invited portal user(s).' },
          ],
        },
      });
      return;
    }

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/member-plan-coverage`) {
      await fulfillJson(route, {
        account: {
          account_id: LONG_ACCOUNT_ID,
          name: 'MVP Account',
          status: 'active',
        },
        summary: {
          member_count: 1,
          covered_member_count: primaryAccountCoverageFollowUp ? 0 : 1,
          sites_needing_follow_up_count: primaryAccountCoverageFollowUp ? 1 : 0,
        },
        members: [
          {
            member_ref: 'user:admin@example.com',
            email: 'admin@example.com',
            identity_type: 'user',
            role: 'user',
            status: 'active',
            covered_site_count: primaryAccountCoverageFollowUp ? 0 : 1,
            sites_needing_follow_up_count: primaryAccountCoverageFollowUp ? 1 : 0,
            accessible_sites: [
              {
                site_id: 'site_mvp',
                site_name: 'MVP Site',
                site_status: 'active',
                plan_id: primaryAccountSubscription.plan_id,
                plan_version_id: primaryAccountSubscription.plan_version_id,
                package_alias: primaryAccountSubscription.package_alias,
                display_package_label: primaryAccountSubscription.display_package_label,
                package_kind: primaryAccountSubscription.package_kind,
                coverage_state: primaryAccountCoverageFollowUp ? 'uncovered' : 'covered',
                covered: !primaryAccountCoverageFollowUp,
                coverage: {
                  covered_by_subscription_id: 'sub_mvp',
                  status: primaryAccountSubscription.status,
                },
              },
            ],
          },
        ],
      });
      return;
    }

    if (pathname === '/api/admin/plans') {
      await fulfillJson(route, {
        tier_templates: [
          {
            tier_id: 'free',
            label: 'Free',
            package_alias: 'Free',
            usage_band: 'Low-volume single-site hosted usage.',
            positioning: 'Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.',
            monthly_included_points: 500,
            site_limit: 1,
            budgets_template: {
              max_runs_per_period: 500,
              max_tokens_per_period: 200000,
              max_cost_per_period: 5,
            },
            concurrency_template: { max_active_runs: 1 },
            max_batch_items: 0,
            automation_enabled: true,
            api_enabled: true,
            openclaw_enabled: true,
            package_operator_note: 'Core capabilities stay available across packages. Free remains the most conservative on points, concurrency, batch headroom, and over-limit handling.',
            policy_baseline: { grace_period_days: 0 },
            canonical_shell: {
              entitlements: {
                ability_families: ['*'],
                channels: ['*'],
                execution_kinds: ['*'],
                execution_tiers: ['cloud'],
                data_classifications: ['*'],
              },
              budgets: {
                max_runs_per_period: 500,
                max_tokens_per_period: 200000,
                max_cost_per_period: 5,
              },
              concurrency: { max_active_runs: 1 },
              policy: { subscription: { grace_period_days: 0 } },
              metadata: {
                tier_id: 'free',
                package_alias: 'Free',
                monthly_included_points: 500,
                site_limit: 1,
                max_batch_items: 0,
                automation_enabled: true,
                api_enabled: true,
                openclaw_enabled: true,
              },
            },
            feature_groups: ['shared_core_surface'],
          },
          {
            tier_id: 'plus',
            label: 'Plus',
            package_alias: 'Plus',
            usage_band: 'Entry paid usage above Free.',
            positioning: 'Entry paid package for small sites that need more hosted headroom.',
            monthly_included_points: 3000,
            site_limit: 3,
            budgets_template: {
              max_runs_per_period: 3000,
              max_tokens_per_period: 600000,
              max_cost_per_period: 15,
            },
            concurrency_template: { max_active_runs: 2 },
            max_batch_items: 15,
            automation_enabled: true,
            api_enabled: true,
            openclaw_enabled: true,
            package_operator_note: 'Plus is the self-serve entry paid package.',
            policy_baseline: { grace_period_days: 3 },
            canonical_shell: {
              entitlements: {
                ability_families: ['*'],
                channels: ['*'],
                execution_kinds: ['*'],
                execution_tiers: ['cloud'],
                data_classifications: ['*'],
              },
              budgets: {
                max_runs_per_period: 3000,
                max_tokens_per_period: 600000,
                max_cost_per_period: 15,
              },
              concurrency: { max_active_runs: 2 },
              policy: { subscription: { grace_period_days: 3 } },
              metadata: {
                tier_id: 'plus',
                package_alias: 'Plus',
                monthly_included_points: 3000,
                site_limit: 3,
                max_batch_items: 15,
                automation_enabled: true,
                api_enabled: true,
                openclaw_enabled: true,
              },
            },
            feature_groups: ['shared_core_surface'],
          },
          {
            tier_id: 'pro',
            label: 'Pro',
            package_alias: 'Pro',
            usage_band: 'Mid-band workflow usage with shared core access.',
            positioning: 'Stable operator-managed package for recurring hosted work with higher headroom.',
            monthly_included_points: 10000,
            site_limit: 5,
            budgets_template: {
              max_runs_per_period: 10000,
              max_tokens_per_period: 2000000,
              max_cost_per_period: 99,
            },
            concurrency_template: { max_active_runs: 2 },
            max_batch_items: 10,
            automation_enabled: true,
            api_enabled: true,
            openclaw_enabled: true,
            package_operator_note: 'Package differences come from points, concurrency, batch limits, and operator headroom.',
            policy_baseline: { grace_period_days: 3, downgrade_policy: 'review_before_downgrade' },
            canonical_shell: {
              entitlements: {
                ability_families: ['*'],
                channels: ['*'],
                execution_kinds: ['*'],
                execution_tiers: ['cloud'],
                data_classifications: ['*'],
              },
              budgets: {
                max_runs_per_period: 10000,
                max_tokens_per_period: 2000000,
                max_cost_per_period: 99,
              },
              concurrency: { max_active_runs: 2 },
              policy: { subscription: { grace_period_days: 3, downgrade_policy: 'review_before_downgrade' } },
              metadata: {
                tier_id: 'pro',
                package_alias: 'Pro',
                monthly_included_points: 10000,
                site_limit: 5,
                max_batch_items: 10,
                automation_enabled: true,
                api_enabled: true,
                openclaw_enabled: true,
              },
            },
            feature_groups: ['shared_core_surface'],
          },
          {
            tier_id: 'agency',
            label: 'Agency',
            package_alias: 'Agency',
            usage_band: 'High-volume multi-site and sustained workflow usage.',
            positioning: 'High-headroom package for multi-site operators, continuous automation, and materially higher hosted workload.',
            monthly_included_points: 50000,
            site_limit: 25,
            budgets_template: {
              max_runs_per_period: 50000,
              max_tokens_per_period: 10000000,
              max_cost_per_period: 499,
            },
            concurrency_template: { max_active_runs: 6 },
            max_batch_items: 100,
            automation_enabled: true,
            api_enabled: true,
            openclaw_enabled: true,
            package_operator_note: 'Core capabilities stay available across packages. Agency provides the highest points budget, concurrency, batch headroom, and policy headroom.',
            policy_baseline: { grace_period_days: 7 },
            canonical_shell: {
              entitlements: {
                ability_families: ['*'],
                channels: ['*'],
                execution_kinds: ['*'],
                execution_tiers: ['cloud'],
                data_classifications: ['*'],
              },
              budgets: {
                max_runs_per_period: 50000,
                max_tokens_per_period: 10000000,
                max_cost_per_period: 499,
              },
              concurrency: { max_active_runs: 6 },
              policy: { subscription: { grace_period_days: 7 } },
              metadata: {
                tier_id: 'agency',
                package_alias: 'Agency',
                monthly_included_points: 50000,
                site_limit: 25,
                max_batch_items: 100,
                automation_enabled: true,
                api_enabled: true,
                openclaw_enabled: true,
              },
            },
            feature_groups: ['shared_core_surface'],
          },
        ],
        items: [
          {
            plan: {
              plan_id: FREE_PLAN_ID,
              name: 'Free',
              status: 'active',
              description: 'Formal production free package.',
              metadata: { source: 'production_default_free_shell_v1', tier_id: 'free', plan_kind: 'default_free' },
              created_at: '2026-04-01T00:00:00Z',
              updated_at: '2026-04-05T00:00:00Z',
            },
            versions: [
              {
                plan_version_id: FREE_PLAN_VERSION_ID,
                version_label: 'Free v1',
                status: 'published',
                currency: 'CNY',
                budgets: {
                  max_runs_per_period: 500,
                  max_tokens_per_period: 200000,
                  max_cost_per_period: 5,
                },
                concurrency: { max_active_runs: 1 },
                metadata: { monthly_included_points: 300, site_limit: 3, max_batch_items: 5 },
                created_at: '2026-04-05T00:00:00Z',
              },
            ],
            latest_version: {
              plan_version_id: FREE_PLAN_VERSION_ID,
              version_label: 'Free v1',
              status: 'published',
              currency: 'CNY',
              budgets: {
                max_runs_per_period: 500,
                max_tokens_per_period: 200000,
                max_cost_per_period: 5,
              },
              concurrency: { max_active_runs: 1 },
              metadata: { monthly_included_points: 300, site_limit: 3, max_batch_items: 5 },
              created_at: '2026-04-05T00:00:00Z',
            },
            tier_summary: {
              tier_id: 'free',
              label: 'Free',
              package_alias: 'Free',
              usage_band: 'Low-volume single-site hosted usage.',
              positioning: 'Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.',
              monthly_included_points: 500,
              site_limit: 1,
              budgets_template: {
                max_runs_per_period: 500,
                max_tokens_per_period: 200000,
                max_cost_per_period: 5,
              },
              concurrency_template: { max_active_runs: 1 },
              max_batch_items: 0,
              automation_enabled: true,
              api_enabled: true,
              openclaw_enabled: true,
              package_operator_note: 'Core capabilities stay available across packages. Free remains the most conservative on points, concurrency, batch headroom, and over-limit handling.',
              policy_baseline: { grace_period_days: 0 },
              feature_groups: ['shared_core_surface'],
            },
            published_version_count: 1,
            subscription_counts: { total: 3, active: 3 },
          },
          {
            plan: {
              plan_id: LONG_PLAN_ID,
              name: 'Pro',
              status: 'active',
              description: 'Package metadata for the operator-managed basic tier.',
              metadata: { source: 'canonical_package_shell_v1', tier_id: 'pro' },
              created_at: '2026-04-01T00:00:00Z',
              updated_at: '2026-04-05T00:00:00Z',
            },
            versions: [
              {
                plan_version_id: LONG_PLAN_VERSION_ID,
                version_label: 'Pro v1',
                status: 'published',
                currency: 'CNY',
                budgets: {
                  max_runs_per_period: 10000,
                  max_tokens_per_period: 2000000,
                  max_cost_per_period: 99,
                },
                concurrency: { max_active_runs: 2 },
                created_at: '2026-04-05T00:00:00Z',
              },
            ],
            latest_version: {
              plan_version_id: LONG_PLAN_VERSION_ID,
              version_label: 'Pro v1',
              status: 'published',
              currency: 'CNY',
              budgets: {
                max_runs_per_period: 10000,
                max_tokens_per_period: 2000000,
                max_cost_per_period: 99,
              },
              concurrency: { max_active_runs: 2 },
              created_at: '2026-04-05T00:00:00Z',
            },
            tier_summary: {
              tier_id: 'pro',
              label: 'Pro',
              package_alias: 'Pro',
              usage_band: 'Mid-band workflow usage with shared core access.',
              positioning: 'Stable operator-managed package for recurring hosted work with higher headroom.',
              monthly_included_points: 10000,
              site_limit: 5,
              budgets_template: {
                max_runs_per_period: 10000,
                max_tokens_per_period: 2000000,
                max_cost_per_period: 99,
              },
              concurrency_template: { max_active_runs: 2 },
              max_batch_items: 10,
              automation_enabled: true,
              api_enabled: true,
              openclaw_enabled: true,
              package_operator_note: 'Package differences come from points, concurrency, batch limits, and operator headroom.',
              policy_baseline: { grace_period_days: 3, downgrade_policy: 'review_before_downgrade' },
              feature_groups: ['shared_core_surface'],
            },
            published_version_count: 1,
            subscription_counts: { total: 1, active: 1 },
          },
        ],
        total: 1,
      });
      return;
    }

    if (pathname === `/api/admin/plans/${LONG_PLAN_ID}`) {
      await fulfillJson(route, {
        plan: {
          plan_id: LONG_PLAN_ID,
          name: 'Pro',
          status: 'active',
          description: 'Package metadata for the operator-managed basic tier.',
          created_at: '2026-04-01T00:00:00Z',
          updated_at: '2026-04-05T00:00:00Z',
        },
        versions: [
          {
            plan_version_id: LONG_PLAN_VERSION_ID,
            version_label: 'Pro v1',
            status: 'published',
            currency: 'CNY',
            entitlements: { hosted: true },
            budgets: {
              max_runs_per_period: 10000,
              max_tokens_per_period: 2000000,
              max_cost_per_period: 99,
            },
            concurrency: { max_active_runs: 2 },
            policy: { grace_period_days: 3 },
            metadata: { source: 'canonical_package_shell_v1', site_limit: 5 },
            created_at: '2026-04-05T00:00:00Z',
          },
        ],
        latest_version: {
          plan_version_id: LONG_PLAN_VERSION_ID,
          version_label: 'Pro v1',
          status: 'published',
          currency: 'CNY',
          entitlements: { hosted: true },
          budgets: {
            max_runs_per_period: 10000,
            max_tokens_per_period: 2000000,
            max_cost_per_period: 99,
          },
          concurrency: { max_active_runs: 2 },
          policy: { grace_period_days: 3 },
          metadata: { source: 'canonical_package_shell_v1', site_limit: 5 },
          created_at: '2026-04-05T00:00:00Z',
        },
        tier_summary: {
          tier_id: 'pro',
          label: 'Pro',
          package_alias: 'Pro',
          usage_band: 'Mid-band workflow usage with shared core access.',
          positioning: 'Stable operator-managed package for recurring hosted work with higher headroom.',
          monthly_included_points: 10000,
          site_limit: 5,
          budgets_template: {
            max_runs_per_period: 10000,
            max_tokens_per_period: 2000000,
            max_cost_per_period: 99,
          },
          concurrency_template: { max_active_runs: 2 },
          max_batch_items: 10,
          automation_enabled: true,
          api_enabled: true,
          openclaw_enabled: true,
          package_operator_note: 'Package differences come from points, concurrency, batch limits, and operator headroom.',
          policy_baseline: { grace_period_days: 3, downgrade_policy: 'review_before_downgrade' },
          feature_groups: ['shared_core_surface'],
        },
        package_fit_cues: [
          {
            code: 'stable',
            severity: 'ok',
            title: 'Package fit is stable',
            detail: 'Current subscriptions fit the package boundary.',
          },
        ],
        subscriptions: [
          {
            subscription: {
              subscription_id: 'sub_mvp',
              site_id: 'site_mvp',
              account_id: LONG_ACCOUNT_ID,
              status: 'past_due',
              plan_version_id: LONG_PLAN_VERSION_ID,
              current_period_end_at: '2026-04-12T00:00:00Z',
            },
            site: { site_id: 'site_mvp', name: 'MVP Site' },
            account: { account_id: LONG_ACCOUNT_ID, name: 'MVP Account' },
          },
        ],
      });
      return;
    }

    if (pathname === `/api/admin/plans/${FREE_PLAN_ID}`) {
      await fulfillJson(route, {
        plan: {
          plan_id: FREE_PLAN_ID,
          name: 'Free',
          status: 'active',
          description: 'Formal production free package.',
          metadata: { source: 'production_default_free_shell_v1', tier_id: 'free', plan_kind: 'default_free' },
          created_at: '2026-04-01T00:00:00Z',
          updated_at: '2026-04-05T00:00:00Z',
        },
        versions: [
          {
            plan_version_id: FREE_PLAN_VERSION_ID,
            version_label: 'Free v1',
            status: 'published',
            currency: 'CNY',
            entitlements: { hosted: true },
            budgets: {
              max_runs_per_period: 500,
              max_tokens_per_period: 200000,
              max_cost_per_period: 5,
            },
            concurrency: { max_active_runs: 1 },
            policy: { grace_period_days: 0 },
            metadata: { source: 'production_default_free_shell_v1', monthly_included_points: 300, site_limit: 3, max_batch_items: 5 },
            created_at: '2026-04-05T00:00:00Z',
          },
        ],
        latest_version: {
          plan_version_id: FREE_PLAN_VERSION_ID,
          version_label: 'Free v1',
          status: 'published',
          currency: 'CNY',
          entitlements: { hosted: true },
          budgets: {
            max_runs_per_period: 500,
            max_tokens_per_period: 200000,
            max_cost_per_period: 5,
          },
          concurrency: { max_active_runs: 1 },
          policy: { grace_period_days: 0 },
          metadata: { source: 'production_default_free_shell_v1', monthly_included_points: 300, site_limit: 3, max_batch_items: 5 },
          created_at: '2026-04-05T00:00:00Z',
        },
        tier_summary: {
          tier_id: 'free',
          label: 'Free',
          package_alias: 'Free',
          usage_band: 'Low-volume single-site hosted usage.',
          positioning: 'Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.',
          monthly_included_points: 500,
          site_limit: 1,
          budgets_template: {
            max_runs_per_period: 500,
            max_tokens_per_period: 200000,
            max_cost_per_period: 5,
          },
          concurrency_template: { max_active_runs: 1 },
          max_batch_items: 0,
          automation_enabled: true,
          api_enabled: true,
          openclaw_enabled: true,
          package_operator_note: 'Free remains the most conservative on points, concurrency, batch headroom, and over-limit handling.',
          policy_baseline: { grace_period_days: 0 },
          feature_groups: ['shared_core_surface'],
        },
        package_fit_cues: [],
        subscriptions: [],
      });
      return;
    }

    if (pathname === `/api/admin/plans/${LONG_PLAN_ID}/versions` && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, {
        plan_version: {
          plan_version_id: String(payload.plan_version_id || LONG_PLAN_VERSION_ID),
          version_label: String(payload.version_label || 'Pro v2'),
          status: String(payload.status || 'published'),
          currency: 'CNY',
          created_at: '2026-04-08T00:00:00Z',
        },
        receipt: {
          event_kind: 'plan_version.publish',
          scope_kind: 'plan_version',
          scope_id: String(payload.plan_version_id || LONG_PLAN_VERSION_ID),
          outcome: 'succeeded',
          effective_summary: 'Plan version is now published.',
        },
      });
      return;
    }

    await fulfillJson(route, {});
  });
}
