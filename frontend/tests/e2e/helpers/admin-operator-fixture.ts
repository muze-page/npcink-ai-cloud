import type { Page, Route } from '@playwright/test';


export const BASE_URL =
  process.env.MAGICK_AI_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.MAGICK_AI_CLOUD_FRONTEND_PORT || '3301'}`;
export const LONG_ACCOUNT_ID = 'acct_mvp_enterprise_primary';
export const LONG_PROVIDER_ID = 'mini-vllm-demo-execution-primary';
export const LONG_RECOGNITION_MODEL_ID = 'model_demo_enterprise_preview_primary';
export const LONG_PLAN_ID = 'plan_basic_primary';
export const LONG_PLAN_VERSION_ID = 'plan_basic_primary_version_v1';
export const FREE_PLAN_ID = 'plan_free';
export const FREE_PLAN_VERSION_ID = 'plan_free_v1';

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
    plan_id: 'plan_basic',
    plan_version_id: 'plan_basic_v1',
    plan_kind: 'tier_paid',
    package_alias: 'Basic',
    package_kind: 'tier_package',
    coverage_state: 'uncovered',
    display_package_label: 'Basic',
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
        created_at: '2026-02-01T00:00:00Z',
      },
      member_count: 1,
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: 'plan_basic',
      package_alias: 'Basic',
      plan_kind: 'tier_paid',
      display_package_label: 'Basic',
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
        account_id: 'acct_dev_baseline',
        name: 'Dev Baseline Account',
        status: 'active',
        created_at: '2026-03-03T00:00:00Z',
      },
      member_count: 0,
      site_count: 1,
      active_subscription_count: 1,
      top_plan_id: 'plan_dev_unlimited',
      package_alias: '',
      plan_kind: '',
      display_package_label: 'Development Unlimited',
      package_kind: 'dev_baseline',
      coverage_state: 'covered',
      primary_subscription_id: 'sub_dev_baseline',
      coverage_follow_up_required: false,
      nearest_expiry_at: '',
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
      name: 'magick_admin_session_token',
      value: 'e2e-admin-session',
      url: BASE_URL,
    },
  ]);

  await page.route('**/api/admin/**', async (route) => {
    const url = new URL(route.request().url());
    const { pathname, searchParams } = url;

    if (pathname === `/api/admin/accounts/${LONG_ACCOUNT_ID}/subscription` && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      const nextPlanId = String(payload.plan_id || primaryAccountSubscription.plan_id);
      const nextPackageAlias =
        nextPlanId === FREE_PLAN_ID ? 'Free' : nextPlanId === 'plan_basic_primary' || nextPlanId === 'plan_basic' ? 'Basic' : 'Basic';
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
        plan_distribution: [{ plan_id: 'plan_basic', count: 1 }],
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

    if (pathname === '/api/admin/subscriptions') {
      await fulfillJson(route, {
        total: 1,
        items: [
          {
            subscription: {
              subscription_id: 'sub_mvp',
              account_id: LONG_ACCOUNT_ID,
              status: 'past_due',
              plan_id: 'plan_basic',
              plan_version_id: 'plan_basic_v1',
              current_period_start_at: '2026-04-01T00:00:00Z',
              current_period_end_at: '2026-04-12T00:00:00Z',
            },
            account: { account_id: LONG_ACCOUNT_ID, name: 'MVP Account' },
            covered_sites: [{ site_id: 'site_mvp', name: 'MVP Site' }],
            coverage: { site_count: 1, package_alias: 'Basic' },
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
          plan_id: 'plan_basic',
          plan_version_id: 'plan_basic_v1',
          current_period_start_at: '2026-04-01T00:00:00Z',
          current_period_end_at: '2026-04-12T00:00:00Z',
        },
        account: { account_id: LONG_ACCOUNT_ID, name: 'MVP Account', status: 'active' },
        covered_sites: [{ site_id: 'site_mvp', name: 'MVP Site', status: 'active' }],
        plan: { plan_id: 'plan_basic', display_name: 'Basic' },
        plan_version: { plan_version_id: 'plan_basic_v1' },
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
          plan_id: 'plan_basic',
          plan_version_id: 'plan_basic_v1',
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
              { member_ref: 'user:admin@example.com', identity_type: 'user_admin', role: 'user_admin', status: 'active' },
            ],
            subscription: {
              subscription_id: 'sub_mvp',
              status: 'past_due',
              plan_id: 'plan_basic',
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
        memberships: [{ member_ref: 'user:admin@example.com', identity_type: 'user_admin', role: 'user_admin', status: 'active' }],
        subscription: {
          subscription_id: 'sub_mvp',
          status: 'past_due',
          plan_id: 'plan_basic',
          plan_version_id: 'plan_basic_v1',
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
        const bindDefaultFree = Boolean(payload.bind_default_free);
        accountItems = [
          {
            account: {
              account_id: accountId,
              name,
              status: 'active',
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
          },
          ...accountItems,
        ];
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
          members_on_dev_baseline: 1,
        },
        items: [
          {
            member_ref: 'user:admin@example.com',
            email: 'admin@example.com',
            identity_type: 'user_admin',
            status: 'active',
            invite_state: 'accepted',
            role: 'user_admin',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 1,
            last_login_at: '2026-04-07T00:00:00Z',
            dev_baseline: true,
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
            identity_type: 'user_admin',
            status: 'pending_invite',
            invite_state: 'pending',
            role: 'user_admin',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 1,
            last_login_at: '',
            dev_baseline: false,
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
            identity_type: 'user_admin',
            status: 'active',
            invite_state: 'accepted',
            role: 'user_admin',
            account_count: 1,
            accessible_site_count: 1,
            sites_needing_follow_up_count: 0,
            last_login_at: '2026-04-08T00:00:00Z',
            dev_baseline: false,
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
      await fulfillJson(route, {
        account: {
          account_id: LONG_ACCOUNT_ID,
          name: 'MVP Account',
          status: 'active',
          created_at: '2026-02-01T00:00:00Z',
        },
        memberships: [{ member_ref: 'user:admin@example.com', identity_type: 'user_admin', role: 'user_admin', status: 'active' }],
        sites: [{ site_id: 'site_mvp', name: 'MVP Site', status: 'active' }],
        subscriptions: [primaryAccountSubscription],
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
            identity_type: 'user_admin',
            role: 'user_admin',
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

    if (pathname === '/api/admin/providers') {
      await fulfillJson(route, {
        items: [
          {
            connection_id: LONG_PROVIDER_ID,
            display_name: 'Mini vLLM Demo',
            provider_type: 'vllm',
            source_role: 'execution_source',
            enabled: true,
            has_secret: true,
            base_url: 'https://mini-vllm.example.com/v1',
            status: 'ok',
            updated_at: '2026-04-05T00:00:00Z',
            last_tested_at: '2026-04-05T00:00:00Z',
            last_sync_at: '2026-04-05T01:00:00Z',
            last_sync_revision: 'rev_demo',
            last_sync_models_total: 4,
            last_test_models_total: 4,
            last_test_provider_id: LONG_PROVIDER_ID,
            metrics: { execution_source: 4, intelligence_source: 0, dual_source: 0 },
          },
        ],
        provider_types: [{ provider_type: 'vllm', label: 'vLLM', default_source_role: 'execution_source' }],
        summary: { healthy_total: 1, error_total: 0, stale_total: 0 },
      });
      return;
    }

    if (pathname === `/api/admin/providers/${LONG_PROVIDER_ID}`) {
      await fulfillJson(route, {
        connection_id: LONG_PROVIDER_ID,
        display_name: 'Mini vLLM Demo',
        provider_type: 'vllm',
        source_role: 'execution_source',
        enabled: true,
        has_secret: true,
        base_url: 'https://mini-vllm.example.com/v1',
        status: 'ok',
        updated_at: '2026-04-05T00:00:00Z',
        last_tested_at: '2026-04-05T00:00:00Z',
        last_sync_at: '2026-04-05T01:00:00Z',
        last_sync_revision: 'rev_demo',
        last_sync_models_total: 4,
        last_test_models_total: 4,
        last_test_provider_id: LONG_PROVIDER_ID,
        config: { timeout_seconds: 30, context_window: 32000 },
      });
      return;
    }

    if (pathname === '/api/admin/models/model_demo') {
      await fulfillJson(route, {
        model_id: 'model_demo',
        provider_id: LONG_PROVIDER_ID,
        family: 'demo',
        feature: 'chat',
        status: 'active',
        context_window: 32000,
        price_input: 0.001,
        price_output: 0.002,
        is_deprecated: false,
        fallback_candidate: false,
        revision: 'rev_demo',
        recommended_profiles: ['default'],
        annotation: {
          recommended: true,
          cost_tier: 'balanced',
          visibility: 'default',
          badges: ['hosted'],
          operator_notes: 'Stable hosted row.',
          updated_at: '2026-04-05T01:00:00Z',
        },
      });
      return;
    }

    if (pathname === '/api/admin/recognition/model' && route.request().method() === 'GET') {
      await fulfillJson(route, {
        provider_id: LONG_PROVIDER_ID,
        model_id: LONG_RECOGNITION_MODEL_ID,
        model_type: 'chat',
        preview_type: 'chat',
        confidence: 0.96,
        price_input: 0.001,
        price_output: 0.002,
        price_source: 'openrouter_model_info',
        price_updated_at: '2026-04-05T01:00:00Z',
        price_confidence: 0.95,
        has_price_conflict: false,
        source: 'openrouter_model_info',
        source_coverage_count: 2,
        source_coverage_sources: ['openrouter_model_info', 'huggingface_model_info'],
        aliases: ['demo-enterprise'],
        short_description: 'High-confidence recognition row for operator review.',
        best_for: 'Hosted chat evaluation and staged rollout review.',
        supports: ['chat', 'tool_use'],
        price_summary: 'Input $0.001 · Output $0.002',
        evidence_sources: ['openrouter_model_info', 'huggingface_model_info'],
        primary_evidence: { source: 'openrouter_model_info', confidence: 0.96 },
        evidence_source_count: 2,
        updated_at: '2026-04-05T01:00:00Z',
        in_hosted_catalog: true,
        has_match_conflict: false,
        has_capability_conflict: false,
        is_new_since_previous_snapshot: false,
        match_conflict_keys: [],
        why_not_in_hosted_catalog: '',
        annotation: {
          review_status: 'reviewed',
          manual_tags: ['stable'],
          operator_notes: 'Reviewed and aligned with hosted catalog metadata.',
          recommended: true,
          cost_tier_override: 'balanced',
          visibility: 'default',
          badges: ['hosted'],
          updated_at: '2026-04-05T01:00:00Z',
        },
        match_keys: ['demo-enterprise'],
        input_modalities: ['text'],
        output_modalities: ['text'],
        capabilities: { chat: true, vision: false, tool_use: true },
        evidence: [
          { source: 'openrouter_model_info', confidence: 0.96 },
          { source: 'huggingface_model_info', confidence: 0.88 },
        ],
        secondary_evidence: [{ source: 'huggingface_model_info', confidence: 0.88 }],
        price_sources: [
          {
            source: 'openrouter_model_info',
            price_source: 'list',
            price_input: 0.001,
            price_output: 0.002,
            price_updated_at: '2026-04-05T01:00:00Z',
            price_confidence: 0.95,
          },
        ],
        capability_sources: [
          {
            source: 'openrouter_model_info',
            model_type: 'chat',
            preview_type: 'chat',
            capabilities: { chat: true, vision: false, tool_use: true },
            confidence: 0.96,
          },
        ],
        hosted_catalog: {
          provider_id: LONG_PROVIDER_ID,
          model_id: 'model_demo',
          feature: 'chat',
          status: 'active',
        },
        hosted_metadata: {
          recommended: true,
          cost_tier: 'balanced',
          visibility: 'default',
          badges: ['hosted'],
          updated_at: '2026-04-05T01:00:00Z',
        },
        pricing: {
          base_currency: 'USD',
          supported_currencies: ['USD', 'CNY'],
          cny_per_usd: 7.2,
          unit: 'per_1m_tokens',
        },
      });
      return;
    }

    if (pathname === '/api/admin/recognition' && route.request().method() === 'GET') {
      await fulfillJson(route, {
        items: [
          {
            provider_id: LONG_PROVIDER_ID,
            model_id: LONG_RECOGNITION_MODEL_ID,
            model_type: 'chat',
            preview_type: 'chat',
            confidence: 0.96,
            price_input: 0.001,
            price_output: 0.002,
            price_source: 'openrouter_model_info',
            price_updated_at: '2026-04-05T01:00:00Z',
            price_confidence: 0.95,
            has_price_conflict: false,
            source: 'openrouter_model_info',
            source_coverage_count: 2,
            source_coverage_sources: ['openrouter_model_info', 'huggingface_model_info'],
            aliases: ['demo-enterprise'],
            short_description: 'High-confidence recognition row for operator review.',
            best_for: 'Hosted chat evaluation and staged rollout review.',
            supports: ['chat', 'tool_use'],
            price_summary: 'Input $0.001 · Output $0.002',
            evidence_sources: ['openrouter_model_info', 'huggingface_model_info'],
            primary_evidence: { source: 'openrouter_model_info', confidence: 0.96 },
            evidence_source_count: 2,
            updated_at: '2026-04-05T01:00:00Z',
            in_hosted_catalog: true,
            has_match_conflict: false,
            has_capability_conflict: false,
            is_new_since_previous_snapshot: false,
            match_conflict_keys: [],
            why_not_in_hosted_catalog: '',
            annotation: {
              review_status: 'reviewed',
              manual_tags: ['stable'],
              operator_notes: 'Reviewed and aligned with hosted catalog metadata.',
              recommended: true,
              cost_tier_override: 'balanced',
              visibility: 'default',
              badges: ['hosted'],
              updated_at: '2026-04-05T01:00:00Z',
            },
          },
        ],
        total: 1,
        pagination: {
          page: 1,
          per_page: 10,
          pages_total: 1,
          offset: 0,
        },
        sort: {
          sort_by: 'provider_id',
          sort_dir: 'asc',
        },
        summary: {
          hosted_catalog_total: 1,
          not_in_hosted_catalog_total: 0,
          candidate_not_in_hosted_total: 0,
          low_confidence_total: 0,
          conflict_total: 0,
          price_conflict_total: 0,
          capability_conflict_total: 0,
          new_models_total: 0,
          disappeared_models_total: 0,
          disappeared_models: [],
          review_status_counts: { reviewed: 1, pending: 0, candidate: 0 },
          sources: ['openrouter_model_info', 'huggingface_model_info'],
          source_counts: { openrouter_model_info: 1, huggingface_model_info: 1 },
          source_trends: [],
          source_runs: [],
          manual_tag_suggestions: ['stable', 'vision', 'candidate'],
        },
        pricing: {
          base_currency: 'USD',
          supported_currencies: ['USD', 'CNY'],
          cny_per_usd: 7.2,
          unit: 'per_1m_tokens',
        },
            latest_publication: {
              revision: 'bundle_demo',
              checksum: 'abcdef1234567890fedcba',
              generated_at: '2026-04-05T01:00:00Z',
              hours_old: 4,
              freshness_status: 'fresh',
            },
            recent_publications: [
              {
                revision: 'bundle_demo',
                checksum: 'abcdef1234567890fedcba',
                generated_at: '2026-04-05T01:00:00Z',
                hours_old: 4,
                freshness_status: 'fresh',
                records_total: 1,
                source_keys: ['openrouter_model_info', 'huggingface_model_info'],
              },
            ],
          },
        },
      });
      return;
    }

    if (pathname === '/api/admin/models') {
      const providerId = searchParams.get('provider_id');
      const items = [
        {
          model_id: 'model_demo',
          provider_id: LONG_PROVIDER_ID,
          family: 'demo',
          feature: 'chat',
          status: 'active',
          context_window: 32000,
          price_input: 0.001,
          price_output: 0.002,
          is_deprecated: false,
          fallback_candidate: false,
          revision: 'rev_demo',
          recommended_profiles: ['default'],
          annotation: {
            recommended: true,
            cost_tier: 'balanced',
            visibility: 'default',
            badges: ['hosted'],
            operator_notes: 'Stable hosted row.',
            updated_at: '2026-04-05T01:00:00Z',
          },
          recognition: {
            matched: true,
            model_type: 'chat',
            preview_type: 'chat',
            confidence: 0.98,
            evidence_sources: ['seed'],
          },
          recognition_review: {
            review_status: 'approved',
            manual_tags: ['stable'],
            operator_notes: 'Approved for hosted serving.',
            updated_at: '2026-04-05T01:00:00Z',
          },
        },
        {
          model_id: 'model_candidate',
          provider_id: LONG_PROVIDER_ID,
          family: 'demo',
          feature: 'chat',
          status: 'active',
          context_window: 32000,
          price_input: 0.0008,
          price_output: 0.0016,
          is_deprecated: false,
          fallback_candidate: true,
          revision: 'rev_demo',
          recommended_profiles: [],
          annotation: {
            recommended: false,
            cost_tier: 'budget',
            visibility: 'advanced',
            badges: ['candidate'],
            operator_notes: 'Available candidate row.',
            updated_at: '2026-04-05T01:00:00Z',
          },
          recognition: {
            matched: true,
            model_type: 'chat',
            preview_type: 'chat',
            confidence: 0.91,
            evidence_sources: ['seed'],
          },
          recognition_review: {
            review_status: 'candidate',
            manual_tags: [],
            operator_notes: '',
            updated_at: '2026-04-05T01:00:00Z',
          },
        },
        {
          model_id: 'model_legacy',
          provider_id: LONG_PROVIDER_ID,
          family: 'demo',
          feature: 'chat',
          status: 'active',
          context_window: 16000,
          price_input: 0.0012,
          price_output: 0.0024,
          is_deprecated: true,
          fallback_candidate: false,
          revision: 'rev_demo',
          recommended_profiles: [],
          annotation: {
            recommended: false,
            cost_tier: 'premium',
            visibility: 'hidden',
            badges: ['legacy'],
            operator_notes: 'Needs cleanup.',
            updated_at: '2026-04-05T01:00:00Z',
          },
          recognition: {
            matched: true,
            model_type: 'chat',
            preview_type: 'chat',
            confidence: 0.88,
            evidence_sources: ['seed'],
          },
          recognition_review: {
            review_status: 'review_needed',
            manual_tags: ['cleanup'],
            operator_notes: 'Deprecated row.',
            updated_at: '2026-04-05T01:00:00Z',
          },
        },
      ].filter((item) => !providerId || item.provider_id === providerId);

      await fulfillJson(route, {
        items,
        total: items.length,
        pagination: {
          page: 1,
          per_page: 10,
          pages_total: 1,
          offset: 0,
        },
        sort: {
          sort_by: 'provider_id',
          sort_dir: 'asc',
        },
        summary: {
          recommended_total: items.filter((item) => item.annotation.recommended).length,
          cost_tier_counts: {},
          visibility_counts: {},
        },
      });
      return;
    }

    if (pathname === '/api/admin/plans') {
      await fulfillJson(route, {
        tier_templates: [
          {
            tier_id: 'starter',
            label: 'Starter',
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
                tier_id: 'starter',
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
            tier_id: 'pro',
            label: 'Pro',
            package_alias: 'Basic',
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
                package_alias: 'Basic',
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
            package_alias: 'Bulk',
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
            package_operator_note: 'Core capabilities stay available across packages. Bulk provides the highest points budget, concurrency, batch headroom, and policy headroom.',
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
                package_alias: 'Bulk',
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
              metadata: { source: 'production_default_free_shell_v1', tier_id: 'starter', plan_kind: 'default_free' },
              created_at: '2026-04-01T00:00:00Z',
              updated_at: '2026-04-05T00:00:00Z',
            },
            versions: [
              {
                plan_version_id: FREE_PLAN_VERSION_ID,
                version_label: 'Free v1',
                status: 'published',
                currency: 'USD',
                budgets: {
                  max_runs_per_period: 500,
                  max_tokens_per_period: 200000,
                  max_cost_per_period: 5,
                },
                concurrency: { max_active_runs: 1 },
                created_at: '2026-04-05T00:00:00Z',
              },
            ],
            latest_version: {
              plan_version_id: FREE_PLAN_VERSION_ID,
              version_label: 'Free v1',
              status: 'published',
              currency: 'USD',
              budgets: {
                max_runs_per_period: 500,
                max_tokens_per_period: 200000,
                max_cost_per_period: 5,
              },
              concurrency: { max_active_runs: 1 },
              created_at: '2026-04-05T00:00:00Z',
            },
            tier_summary: {
              tier_id: 'starter',
              label: 'Starter',
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
              name: 'Basic',
              status: 'active',
              description: 'Package metadata for the operator-managed basic tier.',
              metadata: { source: 'canonical_package_shell_v1', tier_id: 'pro' },
              created_at: '2026-04-01T00:00:00Z',
              updated_at: '2026-04-05T00:00:00Z',
            },
            versions: [
              {
                plan_version_id: LONG_PLAN_VERSION_ID,
                version_label: 'Basic v1',
                status: 'published',
                currency: 'USD',
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
              version_label: 'Basic v1',
              status: 'published',
              currency: 'USD',
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
              package_alias: 'Basic',
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
          name: 'Basic',
          status: 'active',
          description: 'Package metadata for the operator-managed basic tier.',
          created_at: '2026-04-01T00:00:00Z',
          updated_at: '2026-04-05T00:00:00Z',
        },
        versions: [
          {
            plan_version_id: LONG_PLAN_VERSION_ID,
            version_label: 'Basic v1',
            status: 'published',
            currency: 'USD',
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
          version_label: 'Basic v1',
          status: 'published',
          currency: 'USD',
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
          package_alias: 'Basic',
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

    if (pathname === `/api/admin/plans/${LONG_PLAN_ID}/versions` && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, {
        plan_version: {
          plan_version_id: String(payload.plan_version_id || LONG_PLAN_VERSION_ID),
          version_label: String(payload.version_label || 'Basic v2'),
          status: String(payload.status || 'published'),
          currency: 'USD',
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
