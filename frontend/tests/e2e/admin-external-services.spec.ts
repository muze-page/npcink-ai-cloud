import { expect, test, type Page } from '@playwright/test';
import { buildAdminApiEnvelope, installAdminMocks } from './helpers/admin-operator-fixture';

const connections = [
  {
    connection_id: 'external_tavily',
    provider_id: 'tavily',
    provider_type: 'web_search_provider',
    kind: 'web_search_provider',
    display_name: 'Tavily',
    enabled: true,
    configured: true,
    status: 'ready',
    base_url: 'https://api.tavily.com',
    source_role: 'execution_source',
    capability_ids: ['web_search'],
    runtime_profile_ids: ['web-search.managed'],
    config: {},
    metadata: {},
  },
];

async function installExternalServicesHarness(page: Page) {
  await installAdminMocks(page);
  const writes: Array<Record<string, unknown>> = [];
  await page.route('**/api/admin/provider-connections**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({ connections })) });
      return;
    }
    if (request.method() === 'POST' && pathname.endsWith('/test')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({ ok: true })) });
      return;
    }
    if (request.method() === 'POST' || request.method() === 'PATCH') {
      writes.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({})) });
      return;
    }
    await route.fallback();
  });
  return writes;
}

test('fixed external service directory separates search and image runtime settings', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const writes = await installExternalServicesHarness(page);
  await page.goto('/admin/external-services');

  await expect(page.locator('[data-external-service-id="tavily"]')).toBeVisible();
  await expect(page.locator('[data-external-service-id="jina_reader"]')).toBeVisible();
  await expect(page.getByRole('button', { name: /Add|添加/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Delete$|^删除$/i })).toHaveCount(0);
  await expect(page.getByText(/One primary \+ Reader enhancement|主服务单选 \+ Reader 增强/i)).toBeVisible();

  await page.getByRole('tab', { name: /Image sources|图库来源/i }).click();
  await expect(page.locator('[data-external-service-id="unsplash"]')).toBeVisible();
  await expect(page.locator('[data-external-service-id="pixabay"]')).toBeVisible();
  await expect(page.locator('[data-external-service-id="pexels"]')).toBeVisible();
  await expect(page.getByText(/Enabled sources in parallel|已启用来源并行/i, { exact: true }).first()).toBeVisible();

  const unsplash = page.locator('[data-external-service-id="unsplash"]');
  await unsplash.getByLabel(/API key|API Key|Token/i).fill('test-image-key');
  await unsplash.getByRole('checkbox').click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({
    provider_id: 'unsplash',
    kind: 'image_source_provider',
    enabled: true,
    capability_ids: ['image_source'],
    runtime_profile_ids: ['image-source.managed'],
  });
  expect(writes[0]).not.toHaveProperty('priority');
  expect(writes[0]).not.toHaveProperty('note');
  expect(writes[0]).not.toHaveProperty('channel_note');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(1440);
});

test('reader enhancement stays independent and credential clearing disables the service', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const writes = await installExternalServicesHarness(page);
  await page.goto('/admin/external-services');

  const tavily = page.locator('[data-external-service-id="tavily"]');
  await tavily.getByText(/Advanced|高级操作/i, { exact: true }).click();
  await tavily.getByRole('button', { name: /Clear credential and disable|清除凭据并停用/i }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({
    provider_id: 'tavily',
    enabled: false,
    credential: '',
  });

  const reader = page.locator('[data-external-service-id="jina_reader"]');
  await reader.getByRole('checkbox').click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toMatchObject({
    provider_id: 'jina_reader',
    enabled: true,
    source_role: 'reader_enhancement',
    runtime_profile_ids: ['web-search.reader'],
    metadata: {
      ui_source: 'external_services',
      service_role: 'enhancer',
    },
  });
  expect(writes[1]).not.toHaveProperty('priority');
  expect(writes[1]).not.toHaveProperty('note');
});
