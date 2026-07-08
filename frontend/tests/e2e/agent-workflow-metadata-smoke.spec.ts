import { expect, test, type Page } from '@playwright/test';

test.skip(
  !process.env.NPCINK_CLOUD_FRONTEND_BASE_URL,
  'agent/workflow metadata smoke expects a running Cloud dev surface'
);

async function expectNoConsoleFailures(page: Page) {
  const messages: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const text = message.text();
      if (!text.includes('favicon.ico') && !text.startsWith('Failed to load resource:')) {
        messages.push(text);
      }
    }
  });
  page.on('pageerror', (error) => messages.push(error.message));
  return () => expect(messages).toEqual([]);
}

test('admin agent and workflow metadata panels render from Cloud metadata projection responses', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const assertNoConsoleFailures = await expectNoConsoleFailures(page);

  await page.goto('/admin/dev-entry?redirect=%2Fadmin%2Fai-advisor');
  await expect(page).toHaveURL(/\/admin\/ai-advisor/);
  await page.getByText(/AI evaluation details|AI 评估详情/u).click();
  await expect(page.getByText(/Agent boundary|Agent 边界/u)).toBeVisible();
  await expect(page.getByText('internal_ops_advisor_agent', { exact: true })).toBeVisible();
  await expect(page.getByText(/write blocked|Write blocked|禁止写入/u)).toBeVisible();
  await expect(page.getByText(/Cloud Workflow Truth/i)).toBeVisible();

  await page.goto('/admin/ai-resources?view=connections&supplier=capability');
  await expect(page.getByText(/Cloud runtime metadata|Cloud 运行时元数据/u)).toBeVisible();

  await page.goto('/admin/media-observability');
  await expect(page.getByText(/Workflow metadata|工作流元数据/u)).toBeVisible();
  await expect(page.getByText(/Media derivative artifact generation|媒体衍生工件生成/u)).toBeVisible();
  await expect(page.getByText(/whole run offload|整次运行卸载/u).first()).toBeVisible();
  await expect(page.getByText(/return_artifact_unavailable|返回工件不可用/u)).toBeVisible();
  await page.getByText(/Technical metadata|技术元数据/u).click();
  await expect(page.getByText('media_derivative_artifact_generation')).toBeVisible();
  await expect(page.getByText(/short TTL artifact|短 TTL 工件/u).first()).toBeVisible();

  assertNoConsoleFailures();
});
