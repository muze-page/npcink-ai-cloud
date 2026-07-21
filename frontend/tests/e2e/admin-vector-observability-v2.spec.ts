import { expect, test, type Page } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

const vectorData = {
  generated_at: '2026-07-12T12:00:00Z',
  window: { hours: 24, start_at: '2026-07-11T12:00:00Z', end_at: '2026-07-12T12:00:00Z' },
  totals: {
    index_jobs_total: 12,
    index_succeeded_total: 11,
    index_failed_total: 1,
    index_success_rate: 0.9167,
    indexed_documents_total: 320,
    indexed_chunks_total: 1280,
    failed_documents_total: 1,
    avg_index_duration_ms: 840,
    p95_index_duration_ms: 1450,
    search_queries_total: 48,
    search_succeeded_total: 45,
    search_failed_total: 3,
    search_success_rate: 0.9375,
    no_hit_total: 14,
    no_hit_rate: 0.2917,
    avg_search_latency_ms: 92,
    p95_search_latency_ms: 210,
    avg_top1_score: 0.742,
    indexed_site_count: 2,
    current_document_count: 320,
    current_chunk_count: 1280,
  },
  health: { status: 'warning', score: 71, summary: 'No-hit rate requires review.' },
  timeline: [{ bucket_start_at: '2026-07-12T11:00:00Z', index_jobs_total: 12, indexed_chunks_total: 1280, search_queries_total: 48, no_hit_total: 14, failed_total: 4 }],
  intents: [{ intent: 'product_support', queries_total: 48, no_hit_total: 14, no_hit_rate: 0.2917, avg_top1_score: 0.742, avg_latency_ms: 92 }],
  sites: [{ site_id: 'site_mvp', queries_total: 48, no_hit_total: 14, no_hit_rate: 0.2917, avg_top1_score: 0.742, avg_latency_ms: 92, last_search_finished_at: '2026-07-12T11:58:00Z', document_count: 320, chunk_count: 1280, last_indexed_at: '2026-07-12T11:40:00Z' }],
  index_snapshots: [{ site_id: 'site_mvp', document_count: 320, chunk_count: 1280, post_type_counts: { post: 320 }, source_type_counts: { wordpress: 320 }, last_indexed_at: '2026-07-12T11:40:00Z', embedding_provider: 'openai', embedding_model: 'text-embedding-3-small', embedding_dimensions: 1536, vector_backend: 'pgvector', captured_at: '2026-07-12T11:40:00Z' }],
  errors: [{ error_code: 'vector_search_timeout', count: 3, last_seen_at: '2026-07-12T11:58:00Z' }],
};

async function installVectorHarness(page: Page) {
  await installAdminMocks(page);
  const urls: string[] = [];
  let failNext = false;
  await page.route('**/api/admin/vector-observability?*', async (route) => {
    urls.push(route.request().url());
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('temporary vector telemetry failure')) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope(vectorData)) });
  });
  return { urls: () => urls, failNextRequest: () => { failNext = true; } };
}

test('vector observability keeps scope and selected error URL-backed', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installVectorHarness(page);
  await page.goto('/admin/vector-observability');

  await expect(page.locator('[data-ui="vector-error-item"]')).toHaveCount(1);
  await expect(page.locator('#vector-error-inspector')).toContainText('vector_search_timeout');
  await page.locator('[data-ui="vector-error-item"]').click();
  await expect(page).toHaveURL(/focus=vector_search_timeout/);

  await page.getByRole('button', { name: '72h' }).click();
  await expect(page).toHaveURL(/window=72/);
  await expect.poll(() => harness.urls().some((url) => url.includes('window_hours=72'))).toBe(true);
  await page.getByLabel(/Filter by site ID|按站点 ID 筛选/i).fill('site_mvp');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/site=site_mvp/);

  const advanced = page.locator('details').filter({ hasText: /Advanced index snapshots|高级索引快照/i });
  await expect(advanced).not.toHaveAttribute('open', '');

  harness.failNextRequest();
  await page.getByRole('button', { name: /^Refresh$|^刷新$/i }).click();
  await expect(page.getByText(/last successfully loaded vector snapshot|最近一次成功加载的向量观测快照/i)).toBeVisible();
  await expect(page.locator('[data-ui="vector-error-item"]')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('vector observability exits initial loading with a scoped retry', async ({ page }) => {
  await installAdminMocks(page);
  await page.route('**/api/admin/vector-observability?*', async (route) => {
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('vector diagnostics unavailable')) });
  });
  await page.goto('/admin/vector-observability');

  await expect(page.getByRole('heading', { name: /Vector Observability|向量观测/i })).toBeVisible();
  await expect(page.locator('[role="alert"]').filter({ hasText: /vector diagnostics unavailable|Failed to load vector diagnostics|加载向量诊断失败/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Retry$|^重试$/i })).toBeVisible();
});
