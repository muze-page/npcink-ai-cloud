import { expect, test, type Page } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

const mediaData = {
  contract_version: 'magick-media-observability-summary-v2',
  generated_at: '2026-07-12T12:00:00Z',
  workflow_metadata: {},
  window: { hours: 24, start_at: '2026-07-11T12:00:00Z', end_at: '2026-07-12T12:00:00Z' },
  totals: {
    jobs_total: 18,
    succeeded_total: 16,
    failed_total: 2,
    success_rate: 0.8889,
    avg_processing_duration_ms: 680,
    p95_processing_duration_ms: 1320,
    avg_queue_wait_ms: 110,
    source_bytes_total: 18000000,
    output_bytes_total: 9000000,
    bytes_saved_total: 9000000,
    compression_ratio: 0.5,
    delivery_started_count: 7,
    delivery_stream_completed_count: 6,
    delivery_acknowledged_count: 5,
    stream_completion_rate: 0.8571,
    acknowledgement_rate: 0.8333,
    last_finished_at: '2026-07-12T11:58:00Z',
    active_site_count: 2,
    active_account_count: 1,
    watermark_job_count: 3,
    active_artifact_count: 5,
    active_artifact_bytes: 2400000,
  },
  health: { status: 'warning', score: 74, summary: 'Media failures require review.' },
  timeline: [
    { bucket_start_at: '2026-07-12T10:00:00Z', jobs_total: 8, failed_total: 1, bytes_saved_total: 4000000 },
    { bucket_start_at: '2026-07-12T11:00:00Z', jobs_total: 10, failed_total: 1, bytes_saved_total: 5000000 },
  ],
  formats: [{ target_format: 'webp', jobs_total: 18, succeeded_total: 16, failed_total: 2, success_rate: 0.8889, source_bytes_total: 18000000, output_bytes_total: 9000000, bytes_saved_total: 9000000, compression_ratio: 0.5, avg_processing_duration_ms: 680 }],
  sites: [{ site_id: 'site_mvp', jobs_total: 18, succeeded_total: 16, failed_total: 2, success_rate: 0.8889, source_bytes_total: 18000000, output_bytes_total: 9000000, bytes_saved_total: 9000000, compression_ratio: 0.5, avg_processing_duration_ms: 680, last_finished_at: '2026-07-12T11:58:00Z' }],
  errors: [{ error_code: 'image_decode_failed', count: 2, last_seen_at: '2026-07-12T11:58:00Z' }],
  recent_failures: [{ run_id: 'media_run_1', site_id: 'site_mvp', target_format: 'webp', error_code: 'image_decode_failed', source_bytes: 4200000, queue_wait_ms: 120, processing_duration_ms: 780, finished_at: '2026-07-12T11:58:00Z' }],
};

async function installMediaHarness(page: Page) {
  await installAdminMocks(page);
  const urls: string[] = [];
  let failNext = false;
  await page.route('**/api/admin/media-observability?*', async (route) => {
    urls.push(route.request().url());
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('temporary media telemetry failure')) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope(mediaData)) });
  });
  return { urls: () => urls, failNextRequest: () => { failNext = true; } };
}

test('media observability keeps scoped filters and failure evidence URL-backed', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installMediaHarness(page);
  await page.goto('/admin/media-observability');

  await expect(page.locator('[data-ui="media-failure-item"]')).toHaveCount(1);
  await expect(page.locator('#media-failure-inspector')).toContainText('media_run_1');
  await expect(page.locator('#media-failure-inspector')).toContainText('image_decode_failed');

  await page.locator('[data-ui="media-failure-item"]').click();
  await expect(page).toHaveURL(/focus=media_run_1/);
  await page.getByRole('button', { name: '72h' }).click();
  await expect(page).toHaveURL(/window=72/);
  await expect.poll(() => harness.urls().some((url) => url.includes('window_hours=72'))).toBe(true);
  await page.getByRole('button', { name: /^WebP$/i }).click();
  await expect(page).toHaveURL(/format=webp/);
  await page.getByLabel(/Filter by site ID|按站点 ID 筛选/i).fill('site_mvp');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/site=site_mvp/);

  const advanced = page.locator('details').filter({
    hasText: /Advanced workflow and error evidence|高级工作流与错误证据/i,
  });
  await expect(advanced).not.toHaveAttribute('open', '');
  await testInfo.attach('p4-e03-admin-media-observability', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  harness.failNextRequest();
  await page.getByRole('button', { name: /^Refresh$|^刷新$/i }).click();
  await expect(page.getByText(/last successfully loaded media snapshot|最近一次成功加载的媒体观测快照/i)).toBeVisible();
  await expect(page.locator('[data-ui="media-failure-item"]')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('media observability exits initial loading with a scoped retry when the API fails', async ({ page }) => {
  await installAdminMocks(page);
  await page.route('**/api/admin/media-observability?*', async (route) => {
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('media diagnostics unavailable')) });
  });
  await page.goto('/admin/media-observability');

  await expect(page.getByRole('heading', { name: /Media Processing Observability|媒体处理观测/i })).toBeVisible();
  await expect(page.locator('[role="alert"]').filter({ hasText: /media diagnostics unavailable|Failed to load media processing diagnostics|加载媒体处理诊断失败/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Retry$|^重试$/i })).toBeVisible();
  await expect(page.locator('[data-ui="media-failure-item"]')).toHaveCount(0);
});
