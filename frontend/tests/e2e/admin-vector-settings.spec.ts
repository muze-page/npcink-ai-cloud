import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

test('vector settings keeps fixed PC configuration groups and saves without channel priority or notes', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installAdminMocks(page);

  const connections = [
    {
      connection_id: 'embedding_siliconflow',
      provider_id: 'siliconflow',
      provider_type: 'embedding_provider',
      kind: 'embedding_provider',
      display_name: 'SiliconFlow Embedding',
      enabled: true,
      configured: true,
      status: 'ready',
      base_url: 'https://api.siliconflow.cn/v1',
      source_role: 'execution_source',
      capability_ids: ['embedding'],
      runtime_profile_ids: ['embed.default'],
      config: { model_id: 'BAAI/bge-m3', dimensions: 1024 },
      metadata: {},
    },
  ];
  let savedPayload: Record<string, unknown> | null = null;

  await page.route('**/api/admin/provider-connections**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'GET' && pathname === '/api/admin/provider-connections') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', data: { connections } }),
      });
      return;
    }
    if (request.method() === 'POST' && pathname === '/api/admin/provider-connections') {
      savedPayload = request.postDataJSON() as Record<string, unknown>;
      connections.push({
        ...(savedPayload as typeof connections[number]),
        connection_id: String(savedPayload.connection_id),
        configured: true,
        status: 'ready',
        source_role: 'execution_source',
        metadata: {},
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', data: connections.at(-1) }),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto('/admin/vector-settings');
  await expect(page.getByRole('heading', { name: /Vector settings|向量设置/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Embedding model|Embedding 模型/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Vector database|向量数据库/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Result reranking|结果重排/i })).toBeVisible();
  await expect(page.getByText(/Changing the model, dimensions, or database|修改模型、维度或数据库/i).first()).toBeVisible();

  const vectorDatabaseSection = page.locator('[data-vector-group="store"]');
  await page.getByRole('button', { name: /Zilliz Cloud/i }).click();
  await vectorDatabaseSection.getByLabel(/Service URL|服务地址/i).fill('https://zilliz.example.test');
  await vectorDatabaseSection.getByLabel(/API key \/ token|API Key \/ Token/i).fill('zilliz-secret');
  await vectorDatabaseSection.getByLabel(/Database|数据库/i).fill('npcink');
  await vectorDatabaseSection.getByLabel('Collection').fill('site_chunks');
  await vectorDatabaseSection.getByRole('button', { name: /^Save$|^保存$/i }).click();

  await expect.poll(() => savedPayload).not.toBeNull();
  expect(savedPayload).toMatchObject({
    provider_id: 'zilliz',
    kind: 'vector_store_provider',
    enabled: true,
  });
  expect(savedPayload).not.toHaveProperty('priority');
  expect(savedPayload).not.toHaveProperty('note');
  await expect(page.getByRole('status')).toContainText(/Settings saved|设置已保存/i);
  await expect(page.getByRole('link', { name: /Open vector diagnostics|查看向量诊断/i })).toHaveAttribute('href', '/admin/vector-observability');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(1440);
});
