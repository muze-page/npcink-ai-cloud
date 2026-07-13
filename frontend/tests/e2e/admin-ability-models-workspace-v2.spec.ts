import { expect, test, type Page } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

const textInstance = {
  instance_id: 'text.primary',
  provider_id: 'provider_text',
  provider_display_name: 'Text Provider',
  adapter_type: 'openai_compatible',
  model_id: 'text-model-v1',
  endpoint_variant: 'chat_completions',
  region: 'global',
  health_status: 'healthy',
  weight: 100,
  capability_tags: ['text'],
  model_status: 'enabled',
  model_feature: 'text_generation',
};

const embeddingInstance = {
  ...textInstance,
  instance_id: 'embedding.primary',
  provider_id: 'provider_vector',
  provider_display_name: 'Vector Provider',
  model_id: 'embedding-model-v1',
  capability_tags: ['embedding'],
  model_feature: 'embedding',
};

async function installAbilityModelHarness(page: Page) {
  await installAdminMocks(page);
  await page.route('**/api/admin/ai-resources', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', data: { connections: [] } }) });
  });
  await page.route('**/api/admin/ability-models/plugin-routing', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ message: 'writes are not expected in this test' }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          available_text_instances: [textInstance],
          available_vision_instances: [],
          available_image_instances: [],
          available_audio_instances: [],
          available_embedding_instances: [embeddingInstance],
          profiles: [
            {
              profile_id: 'route.short_text',
              group_id: 'content',
              routing_intent: 'content.short_text',
              label: 'Short text',
              description: 'Shared route for short text suggestions.',
              execution_kind: 'text',
              tasks: ['title_generation', 'excerpt_generation'],
              candidate_instance_ids: ['text.primary'],
              timeout_ms: 30000,
              max_timeout_ms: 60000,
              allow_fallback: true,
              max_retries: 1,
              revision: 'rev-1',
              updated_at: '2026-07-12T08:00:00Z',
              status: 'active',
            },
            {
              profile_id: 'route.classification',
              group_id: 'content',
              routing_intent: 'content.classification',
              label: 'Classification',
              description: 'Shared route for classification.',
              execution_kind: 'text',
              tasks: ['content_classification'],
              candidate_instance_ids: ['text.primary'],
              timeout_ms: 25000,
              max_timeout_ms: 60000,
              allow_fallback: false,
              max_retries: 0,
              revision: 'rev-2',
              updated_at: '2026-07-12T08:00:00Z',
              status: 'active',
            },
          ],
        },
      }),
    });
  });
  await page.route('**/api/admin/ability-models/runtime-projection', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          rows: [
            {
              ability_id: 'site_knowledge_embedding',
              label: 'Site Knowledge vectors',
              description: 'Embedding runtime for Site Knowledge.',
              media: 'vector',
              status: 'connected',
              model_kind: 'embedding_model',
              profile_id: 'embed.default',
              provider_id: 'provider_vector',
              model_id: 'embedding-model-v1',
              surface: 'site_knowledge',
              can_configure: true,
              action: 'configure_model',
            },
          ],
        },
      }),
    });
  });
}

test('ability-model workspace is read-first, URL-backed, and mobile safe', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAbilityModelHarness(page);
  await page.goto('/admin/ability-models');

  await expect(page.getByRole('button', { name: /Short text suggestions|短文本建议/i })).toBeVisible();
  await expect(page.locator('#ability-route-inspector')).toContainText(/text-model-v1/i);
  await expect(page.locator('main input')).toHaveCount(0);

  await page.getByRole('button', { name: /Content classification|内容分类/i }).click();
  await expect(page).toHaveURL(/focus=route.classification/);
  await expect(page.locator('#ability-route-inspector')).toContainText(/Classification|内容分类/i);
  await page.reload();
  await expect(page.getByRole('button', { name: /Content classification|内容分类/i })).toHaveAttribute('aria-pressed', 'true');

  await page.getByRole('button', { name: /Cloud runtime dependencies|Cloud 运行依赖/i }).click();
  await expect(page).toHaveURL(/surface=cloud/);
  await expect(page.locator('#cloud-dependency-inspector')).toContainText(/embedding-model-v1/i);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.locator('main input')).toHaveCount(0);
});

test('model candidates stay inside the bounded edit dialogs', async ({ page }) => {
  await installAbilityModelHarness(page);
  await page.goto('/admin/ability-models');
  await expect(page.locator('main input')).toHaveCount(0);

  const configureRouteButton = page.getByRole('button', { name: /^Configure$|^配置$/i });
  await configureRouteButton.click();
  const routeDialog = page.getByRole('dialog', { name: /Configure ability-model route|配置能力模型路由/i });
  await expect(routeDialog).toBeVisible();
  await expect(routeDialog.getByText(/Available models|可选模型/i)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(routeDialog).toHaveCount(0);
  await expect(configureRouteButton).toBeFocused();

  await page.goto('/admin/ability-models?surface=cloud');
  const configureCloudButton = page.getByRole('button', { name: /Configure model|配置模型/i });
  await configureCloudButton.click();
  const cloudDialog = page.getByRole('dialog', { name: /Configure runtime model|配置运行时模型/i });
  await expect(cloudDialog.getByText(/Available vector models|可选向量模型/i)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(cloudDialog).toHaveCount(0);
  await expect(configureCloudButton).toBeFocused();
});
