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

test('admin agent and workflow metadata panels render from Cloud registry responses', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const assertNoConsoleFailures = await expectNoConsoleFailures(page);

  await page.goto('/admin/dev-entry?redirect=%2Fadmin%2Fai-advisor');
  await expect(page).toHaveURL(/\/admin\/ai-advisor/);
  await expect(page.getByText('Agent handoff')).toBeVisible();
  await expect(page.getByText('internal_ops_advisor_agent', { exact: true })).toBeVisible();
  await expect(page.getByText('write blocked', { exact: true })).toBeVisible();
  await expect(page.getByText(/Cloud Workflow Truth/i)).toBeVisible();

  await page.goto('/admin/ai-resources?view=connections&supplier=capability');
  await expect(page.getByText('Workflow metadata')).toBeVisible();
  await expect(page.getByText('external_web_evidence_preflight')).toBeVisible();
  await expect(page.getByText('step_offload')).toBeVisible();
  await expect(page.getByText('wordpress_local')).toBeVisible();
  await expect(page.getByText('return_without_external_evidence')).toBeVisible();

  await page.goto('/admin/media-observability');
  await expect(page.getByText('media_derivative_artifact_generation')).toBeVisible();
  await expect(page.getByText('whole_run_offload')).toBeVisible();
  await expect(page.getByText('short_ttl_artifact')).toBeVisible();
  await expect(page.getByText('return_artifact_unavailable')).toBeVisible();

  assertNoConsoleFailures();
});
