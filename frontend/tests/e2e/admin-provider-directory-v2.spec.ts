import { expect, test, type Page } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

const connections = [
  {
    connection_id: 'model_attention',
    provider_id: 'minimax',
    display_name: 'MiniMax',
    kind: 'minimax',
    enabled: true,
    configured: false,
    status: 'missing_secret',
    base_url: 'https://api.minimax.io/v1',
    capability_ids: ['text_generation'],
    runtime_profile_ids: ['text.ai'],
    model_ids: ['MiniMax-M2.1'],
    last_tested_at: '2026-07-10T08:00:00Z',
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
  {
    connection_id: 'model_ready',
    provider_id: 'openai',
    display_name: 'MQZJ',
    kind: 'openai_compatible',
    enabled: true,
    configured: true,
    status: 'ready',
    base_url: 'https://new-api.example.test/v1',
    capability_ids: ['text_generation'],
    runtime_profile_ids: ['text.ai'],
    model_ids: ['gpt-5.5', 'gpt-5.4-mini'],
    last_tested_at: '2026-07-12T00:25:00Z',
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
  {
    connection_id: 'model_disabled',
    provider_id: 'tei',
    display_name: 'TEI',
    kind: 'tei',
    enabled: false,
    configured: true,
    status: 'disabled',
    base_url: 'https://tei.example.test',
    capability_ids: ['text_generation'],
    runtime_profile_ids: ['text.ai'],
    model_ids: ['bge-m3'],
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
  {
    connection_id: 'search_ready',
    provider_id: 'tavily',
    display_name: 'Tavily Search',
    kind: 'web_search_provider',
    enabled: true,
    configured: true,
    status: 'ready',
    base_url: 'https://api.tavily.com',
    capability_ids: ['web_search'],
    runtime_profile_ids: ['search.ai'],
    last_tested_at: '2026-07-12T01:00:00Z',
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
  {
    connection_id: 'vector_attention',
    provider_id: 'qdrant',
    display_name: 'Qdrant',
    kind: 'vector_store_provider',
    enabled: true,
    configured: false,
    status: 'missing_secret',
    base_url: 'https://qdrant.example.test',
    capability_ids: ['vector_store'],
    runtime_profile_ids: ['vector.ai'],
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
  {
    connection_id: 'embedding_ready',
    provider_id: 'siliconflow',
    display_name: 'SiliconFlow Embedding',
    kind: 'embedding_provider',
    enabled: true,
    configured: true,
    status: 'ready',
    base_url: 'https://api.siliconflow.cn/v1',
    capability_ids: ['embedding'],
    runtime_profile_ids: ['embed.default'],
    managed_by: 'cloud_provider_connections',
    metadata: {},
  },
];

async function installProviderDirectoryHarness(page: Page) {
  await installAdminMocks(page);
  let requestCount = 0;
  await page.route('**/api/admin/ai-resources', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    requestCount += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          surface: 'admin_ai_resources',
          connections,
          capabilities: [],
          capability_matrix: [],
          runtime_resolution: [],
          feature_model_usage: [],
          runtime_profiles: [],
          boundary: {
            direct_wordpress_write: false,
            final_writes: 'excluded',
            secret_exposure: 'masked',
            not_a_control_plane: true,
          },
        },
      }),
    });
  });
  await page.route('**/api/admin/provider-connections/*/test', async (route) => {
    const connectionId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-2) || '');
    const connection = connections.find((item) => item.connection_id === connectionId);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          connection_id: connectionId,
          provider_id: connection?.provider_id || 'unknown',
          kind: connection?.kind || 'unknown',
          status: 'ready',
          stage: 'config_preflight',
          ok: true,
          error_code: '',
          message: 'provider runtime configuration is present',
          tested_at: '2026-07-12T02:00:00Z',
          receipt: {
            event_kind: 'provider_connection.test',
            scope_kind: 'provider_connection',
            scope_id: connectionId,
            outcome: 'succeeded',
          },
        },
      }),
    });
  });
  await page.route('**/api/admin/provider-connections', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const payload = route.request().postDataJSON() as { connection_id?: string; provider_id?: string };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          connection_id: payload.connection_id || 'openai_compatible',
          provider_id: payload.provider_id || 'openai',
          receipt: {
            event_kind: 'provider_connection.save',
            scope_kind: 'provider_connection',
            scope_id: payload.connection_id || 'openai_compatible',
            outcome: 'succeeded',
          },
        },
      }),
    });
  });
  return { getRequestCount: () => requestCount };
}

test('model supplier queue keeps URL-backed focus and removes fixed-width table behavior', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installProviderDirectoryHarness(page);
  await page.goto('/admin/ai-resources');

  await expect(page.locator('[data-ui="supplier-summary-strip"]')).toBeVisible();
  await expect(page.locator('[data-ui="model-supplier-directory"] [data-connection-id]')).toHaveCount(3);
  await expect(page.locator('[data-connection-id="embedding_ready"]')).toHaveCount(0);
  await expect(page.locator('table')).toHaveCount(0);
  expect(harness.getRequestCount()).toBe(1);

  await page.locator('[data-connection-id="model_ready"]').click();
  await expect(page).toHaveURL(/focus=model_ready/);
  await expect(page.locator('[data-ui="supplier-inspector"]')).toContainText('MQZJ');
  await page.reload();
  await expect(page.locator('[data-connection-id="model_ready"]')).toHaveAttribute('aria-pressed', 'true');

  await page.getByLabel(/^Status$|^状态$/i).selectOption('ready');
  await expect(page).toHaveURL(/status=ready/);
  await expect(page.locator('[data-ui="model-supplier-directory"] [data-connection-id]')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(await page.locator('[data-ui="model-supplier-directory"]').evaluate((element) => element.getBoundingClientRect().top)).toBeLessThan(700);
});

test('model supplier workspace does not expose capability-service controls', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installProviderDirectoryHarness(page);
  await page.goto('/admin/ai-resources');

  await expect(page.getByRole('button', { name: /Add model supplier|添加模型供应商/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Add capability supplier|添加能力供应商/i })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: /Capability suppliers|能力供应商/i })).toHaveCount(0);
  await expect(page.locator('[data-ui="capability-supplier-directory"]')).toHaveCount(0);
  await expect(page.locator('[data-connection-id="search_ready"]')).toHaveCount(0);
});

test('supplier inspector keeps test feedback and destructive confirmation beside the selected supplier', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installProviderDirectoryHarness(page);
  await page.goto('/admin/ai-resources?focus=model_ready');

  const inspector = page.locator('[data-ui="supplier-inspector"]');
  await inspector.getByRole('button', { name: /^Test$|^测试$/i }).click();
  await expect(inspector.getByRole('status').filter({ hasText: /Test passed|连接测试通过/i })).toBeVisible();

  await inspector.getByRole('button', { name: /^Delete$|^删除$/i }).click();
  await expect(inspector.getByRole('alert').filter({ hasText: /removes this runtime connection|移除这条运行时连接/i })).toBeVisible();
  await expect(inspector.getByRole('button', { name: /Confirm delete|确认删除/i })).toBeVisible();
  await inspector.getByRole('button', { name: /^Cancel$|^取消$/i }).click();
  await expect(inspector.getByRole('button', { name: /Confirm delete|确认删除/i })).toHaveCount(0);
});

test('provider configuration dialog supports PC keyboard entry, focus loop, and Escape recovery', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installProviderDirectoryHarness(page);
  await page.goto('/admin/ai-resources');

  const addButton = page.getByRole('button', { name: /Add model supplier|添加模型供应商/i });
  await addButton.click();
  const dialog = page.getByRole('dialog', { name: /Add model supplier|添加模型供应商|Add provider|添加供应商/i });
  await expect(dialog).toBeVisible();

  const closeButton = dialog.getByRole('button', { name: /^Close$|^关闭$/i });
  await expect(closeButton).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: /Save and test provider|保存并测试供应商/i })).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(addButton).toBeFocused();

});

test('save and test closes the dialog, uses a compact toast, and keeps the receipt near the toolbar', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installProviderDirectoryHarness(page);
  await page.goto('/admin/ai-resources');

  await page.getByRole('button', { name: /Add model supplier|添加模型供应商/i }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/API Key|Credential|凭据/i).fill('test-secret');
  await dialog.getByRole('button', { name: /Save and test provider|保存并测试供应商/i }).click();

  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('status').filter({ hasText: /saved and tested|已保存并完成测试/i })).toBeVisible();
  await expect(page.locator('main [role="status"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Latest operation|最近操作/i })).toBeVisible();
});
