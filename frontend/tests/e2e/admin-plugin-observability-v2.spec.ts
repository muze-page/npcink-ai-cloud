import { expect, test, type Page } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

const pluginObservabilityData = {
  generated_at: '2026-07-12T12:00:00Z',
  totals: {
    events_total: 40,
    ok_total: 36,
    error_total: 4,
    success_rate: 0.9,
    avg_latency_ms: 640,
    active_site_count: 2,
    active_plugin_count: 3,
    last_seen_at: '2026-07-12T11:58:00Z',
  },
  health: { status: 'warning', score: 72, summary: 'Plugin telemetry needs review.', reasons: ['error_rate'] },
  attention: [
    {
      attention_key: 'attention-plugin-errors',
      severity: 'warning',
      code: 'plugin_observability.error_rate_elevated',
      title: 'Elevated plugin error rate',
      detail: 'Plugin errors require review.',
      suggested_action: 'Review the linked metadata and local plugin logs.',
      workflow_status: 'active',
      site_id: 'site_mvp',
      plugin_slug: 'npcink-cloud-addon',
      event_kind: 'runtime_request',
      error_code: 'provider_timeout',
      state: null,
    },
  ],
  attention_workflow: { active: 1, acknowledged: 0, muted: 0, resolved: 0, total: 1, needs_attention: 1 },
  digest: { period_label: 'daily', window_hours: 24, headline: '', bullets: [], top_plugin_slug: 'npcink-cloud-addon', top_error_code: 'provider_timeout' },
  plugins: [
    { plugin_slug: 'npcink-cloud-addon', events_total: 24, ok_total: 20, error_total: 4, success_rate: 0.8333, avg_latency_ms: 710, last_seen_at: '2026-07-12T11:58:00Z', event_kinds: [{ event_kind: 'runtime_request', events_total: 24, error_total: 4, success_rate: 0.8333, avg_latency_ms: 710, last_seen_at: '2026-07-12T11:58:00Z' }] },
  ],
  sites: [
    { site_id: 'site_mvp', events_total: 24, error_total: 4, ok_total: 20, success_rate: 0.8333, avg_latency_ms: 710, plugin_count: 1, last_seen_at: '2026-07-12T11:58:00Z', health: { status: 'warning', score: 70, summary: 'Errors need review.', reasons: ['error_rate'] } },
  ],
  timeline: [
    { bucket_start_at: '2026-07-12T10:00:00Z', bucket_end_at: '2026-07-12T11:00:00Z', bucket_hours: 1, events_total: 18, ok_total: 16, error_total: 2, success_rate: 0.8889, avg_latency_ms: 620 },
    { bucket_start_at: '2026-07-12T11:00:00Z', bucket_end_at: '2026-07-12T12:00:00Z', bucket_hours: 1, events_total: 22, ok_total: 20, error_total: 2, success_rate: 0.9091, avg_latency_ms: 660 },
  ],
  errors: [{ site_id: 'site_mvp', plugin_slug: 'npcink-cloud-addon', event_kind: 'runtime_request', error_code: 'provider_timeout', count: 4, last_seen_at: '2026-07-12T11:58:00Z' }],
  recent_errors: [{ site_id: 'site_mvp', plugin_slug: 'npcink-cloud-addon', event_kind: 'runtime_request', error_code: 'provider_timeout', status: 'error', ability_id: 'content_summary', proposal_id: '', route: '/v1/runtime/run', received_at: '2026-07-12T11:58:00Z' }],
  window: { hours: 24, start_at: '2026-07-11T12:00:00Z', end_at: '2026-07-12T12:00:00Z' },
};

async function installPluginObservabilityHarness(page: Page, responseData = pluginObservabilityData) {
  await installAdminMocks(page);
  let statePostCount = 0;
  const getUrls: string[] = [];
  let failNextGet = false;
  await page.route('**/api/admin/plugin-observability/attention-state', async (route) => {
    statePostCount += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({ updated: true })) });
  });
  await page.route('**/api/admin/plugin-observability?*', async (route) => {
    getUrls.push(route.request().url());
    if (failNextGet) {
      failNextGet = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('temporary plugin telemetry failure')) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope(responseData)) });
  });
  return {
    getStatePostCount: () => statePostCount,
    getUrls: () => getUrls,
    failNextRequest: () => { failNextGet = true; },
  };
}

test('plugin observability uses URL-backed scope and a queue-inspector watch workflow', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installPluginObservabilityHarness(page);
  await page.goto('/admin/plugin-observability');

  await expect(page.locator('[data-ui="plugin-attention-item"]')).toHaveCount(1);
  await expect(page.locator('#plugin-attention-inspector')).toContainText(/site_mvp/);
  await expect(page.locator('#plugin-attention-inspector')).toContainText(/provider_timeout/);
  await expect(page.locator('#plugin-attention-inspector').getByRole('button')).toHaveCount(3);

  await page.locator('[data-ui="plugin-attention-item"]').click();
  await expect(page).toHaveURL(/focus=attention-plugin-errors/);
  await page.getByRole('button', { name: '72h' }).click();
  await expect(page).toHaveURL(/window=72/);
  await expect.poll(() => harness.getUrls().some((url) => url.includes('window_hours=72'))).toBe(true);

  await page.getByRole('button', { name: /^Cloud Addon$/i }).click();
  await expect(page).toHaveURL(/plugin=npcink-cloud-addon/);
  await page.getByLabel(/Filter by site ID|按站点 ID 筛选/i).fill('site_mvp');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/site=site_mvp/);

  await page.locator('#plugin-attention-inspector').getByRole('button', { name: /Acknowledge|确认/i }).click();
  await expect.poll(() => harness.getStatePostCount()).toBe(1);
  await expect(page.getByText(/Watch item state updated|关注项状态已更新/i)).toBeVisible();

  harness.failNextRequest();
  await page.getByRole('button', { name: /^Refresh$|^刷新$/i }).click();
  await expect(page.getByText(/last successfully loaded plugin snapshot|最近一次成功加载的插件观测快照/i)).toBeVisible();
  await expect(page.locator('[data-ui="plugin-attention-item"]')).toHaveCount(1);
});

test('plugin observability remains readable at 390px without horizontal page overflow', async ({ page }) => {
  await installPluginObservabilityHarness(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/admin/plugin-observability');

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.locator('[data-ui="plugin-attention-item"]')).toBeVisible();
  await expect(page.locator('#plugin-attention-inspector')).toContainText(/provider_timeout/);
});

test('zero event volume does not hide an existing watch item', async ({ page }) => {
  await installPluginObservabilityHarness(page, {
    ...pluginObservabilityData,
    totals: { ...pluginObservabilityData.totals, events_total: 0, ok_total: 0, error_total: 0, success_rate: 0, avg_latency_ms: 0 },
    plugins: [],
    sites: [],
    timeline: [],
    errors: [],
    recent_errors: [],
  });
  await page.goto('/admin/plugin-observability');

  await expect(page.locator('[data-ui="plugin-attention-item"]')).toHaveCount(1);
  await expect(page.locator('#plugin-attention-inspector')).toContainText(/provider_timeout/);
  await expect(page.getByRole('heading', { name: /Events and errors|事件与错误/i })).toHaveCount(0);
});
