import { expect, test } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
} from './helpers/admin-operator-fixture';

const BASE_URL =
  process.env.NPCINK_CLOUD_FRONTEND_BASE_URL ||
  `http://127.0.0.1:${process.env.NPCINK_CLOUD_FRONTEND_PORT || '3301'}`;

function setting(
  settingId: string,
  status: 'ready' | 'disabled' | 'missing_config',
  config: Record<string, unknown>,
  secrets: Record<string, { configured: boolean; display: string }> = {}
) {
  return {
    setting_id: settingId,
    enabled: status !== 'disabled',
    configured: status === 'ready',
    status,
    config,
    secrets,
    last_tested_at: status === 'ready' ? '2026-07-12T06:00:00Z' : '',
    last_error_code: '',
    last_error_message: '',
  };
}

test('service settings v2 preserves dirty input, guards navigation, validates, saves, and keeps one active form', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  let publicBaseUrl = 'https://cloud.example.test';
  let settingsReadCount = 0;
  let failNextPortalSave = false;

  await page.context().addCookies([
    { name: 'npcink_admin_session_token', value: 'e2e-admin-session', url: BASE_URL },
  ]);
  await page.route('**/admin/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope({
        principal_id: 'platform:operator-e2e',
        identity_type: 'platform_admin',
      })),
    });
  });
  await page.route('**/api/admin/service-settings**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/admin/service-settings' && route.request().method() === 'GET') {
      settingsReadCount += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildAdminApiEnvelope({
          settings: {
            portal_public: setting('portal_public', 'ready', { public_base_url: publicBaseUrl }),
            qq_login: setting('portal_qq_login', 'disabled', { client_id: '', redirect_uri: '' }, {
              client_secret: { configured: false, display: '' },
            }),
            portal_email: setting('portal_email', 'ready', {
              smtp_host: 'smtp.example.test',
              smtp_port: 465,
              smtp_username: 'mail@example.test',
              smtp_use_ssl: true,
              smtp_use_starttls: false,
              smtp_timeout_seconds: 20,
              from_email: 'mail@example.test',
              from_name: 'Npcink AI Cloud',
              reply_to: '',
            }, { smtp_password: { configured: true, display: '••••••••' } }),
            alipay_payment: setting('payment_alipay', 'disabled', {
              app_id: '', notify_url: '', return_url: '',
            }, {
              private_key: { configured: false, display: '' },
              public_key: { configured: false, display: '' },
            }),
          },
        })),
      });
      return;
    }
    if (url.pathname === '/api/admin/service-settings/portal-public' && route.request().method() === 'PATCH') {
      if (failNextPortalSave) {
        failNextPortalSave = false;
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify(buildAdminApiErrorEnvelope('temporary service settings failure')),
        });
        return;
      }
      const payload = route.request().postDataJSON() as { public_base_url?: string };
      publicBaseUrl = String(payload.public_base_url || publicBaseUrl);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildAdminApiEnvelope(setting('portal_public', 'ready', { public_base_url: publicBaseUrl }))),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildAdminApiEnvelope({})) });
  });

  await page.goto('/admin/service-settings');
  await expect(page.getByRole('heading', { name: /^Service Settings$|^服务配置$/i })).toBeVisible();
  await expect(page.getByRole('tab')).toHaveCount(4);
  await expect(page.locator('form:visible')).toHaveCount(1);
  expect(settingsReadCount).toBe(1);

  const baseUrlInput = page.getByRole('textbox', { name: /Base URL|基础 URL/i });
  const saveBaseUrl = page.getByRole('button', { name: /Save base URL|保存基础地址/i });
  await baseUrlInput.fill('not-a-url');
  await expect(page.getByText(/valid HTTP or HTTPS|有效的 HTTP 或 HTTPS/i)).toBeVisible();
  await expect(saveBaseUrl).toBeDisabled();

  await baseUrlInput.fill('https://new.example.test');
  await expect(page.getByText(/Unsaved changes|存在未保存更改/i)).toBeVisible();
  const portalPanel = page.locator('#service-settings-portal');
  await expect(portalPanel.locator('[data-ui="service-settings-active-state"]')).toBeVisible();
  await expect(page.getByRole('tab', { name: /Portal URL.*Unsaved|门户地址.*未保存/i })).toBeVisible();
  await expect(saveBaseUrl).toBeEnabled();

  await page.getByRole('tab', { name: /QQ login|QQ 登录/i }).click();
  const discardDialog = page.getByRole('dialog');
  await expect(discardDialog).toContainText(/Discard unsaved changes|放弃未保存更改/i);
  await discardDialog.getByRole('button', { name: /^Cancel$|^取消$/i }).click();
  await expect(baseUrlInput).toHaveValue('https://new.example.test');
  await expect(page.getByRole('tab', { name: /Portal URL|门户地址/i })).toHaveAttribute('aria-selected', 'true');

  await page.getByRole('link', { name: /^Customers$|^客户$/i }).click();
  const leaveDialog = page.getByRole('dialog');
  await expect(leaveDialog).toContainText(/Leave with unsaved changes|放弃更改并离开/i);
  await leaveDialog.getByRole('button', { name: /^Cancel$|^取消$/i }).click();
  await expect(page).toHaveURL(/\/admin\/service-settings$/);

  await page.getByRole('tab', { name: /QQ login|QQ 登录/i }).click();
  await page.getByRole('dialog').getByRole('button', { name: /Discard and switch|放弃并切换/i }).click();
  await expect(page.getByRole('tab', { name: /QQ login|QQ 登录/i })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('form:visible')).toHaveCount(1);
  await page.getByRole('tab', { name: /Portal URL|门户地址/i }).click();
  await expect(baseUrlInput).toHaveValue('https://cloud.example.test');

  await baseUrlInput.fill('https://saved.example.test');
  failNextPortalSave = true;
  await saveBaseUrl.click();
  await expect(page.getByText(/configuration action failed|配置操作失败/i)).toBeVisible();
  await expect(baseUrlInput).toHaveValue('https://saved.example.test');
  await expect(saveBaseUrl).toBeEnabled();

  await saveBaseUrl.click();
  await expect(page.getByText(/Service setting updated|服务配置已更新/i)).toBeVisible();
  await expect(baseUrlInput).toHaveValue('https://saved.example.test');
  await expect(saveBaseUrl).toBeDisabled();
  expect(settingsReadCount).toBe(2);

  await page.getByRole('tab', { name: /QQ login|QQ 登录/i }).click();
  await page.getByRole('switch', { name: /Enable QQ quick login|启用 QQ 快捷登录/i }).click();
  await page.getByRole('textbox', { name: 'App ID' }).fill('qq-app-e2e');
  await expect(page.getByRole('button', { name: /Check QQ settings|检查 QQ 配置/i })).toBeDisabled();
  await expect(page.getByText(/Enter the QQ App Secret|请输入 QQ App Secret/i)).toBeVisible();
  await page.getByRole('button', { name: /Restore saved values|恢复已保存值/i }).click();

  await page.getByRole('tab', { name: /Payment settings|支付配置/i }).click();
  await expect(page.locator('#service-settings-payment [data-ui="service-settings-high-risk"]')).toContainText(/High-risk payment configuration|高风险支付配置/i);
  await page.getByRole('tab', { name: /QQ login|QQ 登录/i }).click();

  await page.getByRole('tab', { name: /Email settings|邮件配置/i }).click();
  const previewButton = page.getByRole('button', { name: /Preview email templates|预览邮件模板/i });
  await previewButton.click();
  const previewDialog = page.getByRole('dialog', { name: /Preview email|预览邮件效果/i });
  await expect(previewDialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(previewDialog).toHaveCount(0);
  await expect(previewButton).toBeFocused();

  await page.getByRole('tab', { name: /QQ login|QQ 登录/i }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('form:visible')).toHaveCount(1);
  // Let responsive transitions settle before measuring the final mobile layout.
  await page.waitForTimeout(250);
  const mobileLayout = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    return {
      viewportWidth,
      scrollWidth: document.documentElement.scrollWidth,
      offenders: [...document.querySelectorAll<HTMLElement>('body *')]
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName,
            text: String(element.textContent || '').trim().slice(0, 50),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
          };
        })
        .filter((item) => item.left < -1 || item.right > viewportWidth + 1)
        .slice(0, 8),
    };
  });
  expect(mobileLayout).toEqual({ viewportWidth: 390, scrollWidth: 390, offenders: [] });
});

test('service settings initial failure preserves the PC shell and bounded retry', async ({ page }) => {
  let attempts = 0;
  await page.context().addCookies([
    { name: 'npcink_admin_session_token', value: 'e2e-admin-session', url: BASE_URL },
  ]);
  await page.route('**/admin/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope({
        principal_id: 'platform:operator-e2e',
        identity_type: 'platform_admin',
      })),
    });
  });
  await page.route('**/api/admin/service-settings', async (route) => {
    attempts += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiErrorEnvelope('service settings unavailable')),
    });
  });

  await page.goto('/admin/service-settings');
  await expect(page.getByRole('heading', { name: /^Service Settings$|^服务配置$/i })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: /service settings unavailable|服务配置/i })).toBeVisible();
  await page.getByRole('button', { name: /^Retry$|^重试$/i }).click();
  await expect.poll(() => attempts).toBe(2);
  await expect(page).toHaveURL(/\/admin\/service-settings$/);
});
