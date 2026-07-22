import { expect, test } from '@playwright/test';

function envelope(data: unknown) {
  return {
    status: 'ok',
    error_code: '',
    message: 'ok',
    data,
    meta: { trace_id: 'trace-setup-e2e', revision: 'setup-e2e-v1' },
  };
}

test('first install keeps secrets in memory and reveals the admin key once', async ({ page }) => {
  const adminKey = 'nca_admin_setup_e2e_only';
  const setupCode = 'nca_setup_setup_e2e_only';
  const databasePassword = 'database-password-e2e-only';
  let installRequest: { headers: Record<string, string>; body: Record<string, unknown> } | null = null;

  await page.route('**/api/setup/state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope({
        installation_state: 'pending',
        setup_revision: 'setup-v1',
        retry_allowed: true,
      })),
    });
  });

  await page.route('**/api/setup/session', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ setup_code: setupCode });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope({
        installation_state: 'pending',
        setup_revision: 'setup-v1',
        retry_allowed: true,
        expires_in_seconds: 900,
      })),
    });
  });

  await page.route('**/api/setup/database/test', async (route) => {
    const request = route.request().postDataJSON() as Record<string, unknown>;
    expect(request.password).toBe(databasePassword);
    expect(request.ssl_mode).toBe('verify-full');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope({
        postgres_major_version: 18,
        ssl_mode: 'verify-full',
        database_empty: true,
        alembic_state: 'empty',
        latency_ms: 12,
        max_connections: 100,
      })),
    });
  });

  await page.route('**/api/setup/install', async (route) => {
    installRequest = {
      headers: route.request().headers(),
      body: route.request().postDataJSON() as Record<string, unknown>,
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope({ admin_key: adminKey, next_url: '/admin/login' })),
    });
  });

  const blockedAdminApi = await page.request.get('/api/admin/overview');
  expect(blockedAdminApi.status()).toBe(503);
  expect((await blockedAdminApi.json()).error_code).toBe('setup.installation_required');
  const frontendHealth = await page.request.get('/api/health');
  expect(frontendHealth.status()).toBe(200);
  expect((await frontendHealth.json()).status).toBe('healthy');
  const frontendHealthHead = await page.request.head('/api/health');
  expect(frontendHealthHead.status()).toBe(200);
  const frontendHealthPost = await page.request.post('/api/health');
  expect(frontendHealthPost.status()).toBe(503);
  expect((await frontendHealthPost.json()).error_code).toBe('setup.installation_required');
  const disguisedAdminApi = await page.request.get('/api/admin/export.png');
  expect(disguisedAdminApi.status()).toBe(503);
  expect((await disguisedAdminApi.json()).error_code).toBe('setup.installation_required');
  const unknownSetupApi = await page.request.post('/api/setup/not-allowed', { data: {} });
  expect(unknownSetupApi.status()).toBe(404);
  expect((await unknownSetupApi.json()).error_code).toBe('proxy.setup_route_not_allowed');
  const adminPageGate = await page.request.get('/admin', { maxRedirects: 0 });
  expect(adminPageGate.status()).toBe(307);
  expect(adminPageGate.headers().location).toMatch(/\/setup$/);

  await page.goto('/setup');
  await expect(page.getByRole('heading', { name: /安装 Cloud|Set up Cloud/i })).toBeVisible();
  await expect(page.getByRole('list', { name: /安装进度|Installation progress/i })).toBeVisible();

  await page.getByLabel(/安装码|Setup code/i).fill(setupCode);
  await page.getByRole('button', { name: /验证安装码|Verify setup code/i }).click();

  await page.getByLabel(/Cloud 名称|Cloud name/i).fill('Npcink Validation Cloud');
  await page.getByLabel(/Cloud 公网地址|Public Cloud URL/i).fill('https://cloud.example.com');
  await page.getByRole('button', { name: /下一步|Next/i }).click();

  await page.getByLabel(/RDS 私网地址|Private RDS host/i).fill('pgm-private.pg.rds.aliyuncs.com');
  await page.getByLabel(/^端口$|^Port$/i).fill('5432');
  await page.getByLabel(/^数据库$|^Database$/i).fill('npcink_cloud');
  await page.getByLabel(/^用户名$|^Username$/i).fill('npcink_app');
  await page.getByLabel(/^密码$|^Password$/i).fill(databasePassword);
  await page.getByLabel(/RDS CA 证书|RDS CA certificate/i).fill('-----BEGIN CERTIFICATE-----\nTEST-ONLY\n-----END CERTIFICATE-----');
  await page.getByRole('button', { name: /测试数据库|Test database/i }).click();
  await expect(page.getByText(/数据库验证通过|Database validation passed/i)).toBeVisible();

  const browserStorage = await page.evaluate(() => ({
    local: JSON.stringify(window.localStorage),
    session: JSON.stringify(window.sessionStorage),
    url: window.location.href,
  }));
  expect(browserStorage.local).not.toContain(setupCode);
  expect(browserStorage.local).not.toContain(databasePassword);
  expect(browserStorage.session).not.toContain(setupCode);
  expect(browserStorage.session).not.toContain(databasePassword);
  expect(browserStorage.url).not.toContain(setupCode);
  expect(browserStorage.url).not.toContain(databasePassword);

  await page.getByRole('button', { name: /下一步|Next/i }).click();
  await expect(page.getByText('pgm-private.pg.rds.aliyuncs.com:5432/npcink_cloud')).toBeVisible();
  await expect(page.getByText(databasePassword)).toHaveCount(0);
  await page.getByRole('button', { name: /初始化 Cloud|Initialize Cloud/i }).click();

  await expect(page.getByRole('heading', { name: /立即保存管理员密钥|Save the admin key now/i })).toBeVisible();
  await expect(page.locator('[data-setup-installation-state="complete"]')).toBeVisible();
  await expect(page.getByRole('textbox', { name: /^管理员密钥$|^Admin key$/i })).toHaveValue(adminKey);
  const openAdmin = page.getByRole('button', { name: /打开后台登录|Open admin login/i });
  await expect(openAdmin).toBeDisabled();
  await page.getByLabel(/我已经把管理员密钥|I saved this admin key/i).check();
  await expect(openAdmin).toBeEnabled();

  expect(installRequest).not.toBeNull();
  expect(installRequest?.headers['idempotency-key']).toMatch(/^cloud_first_install_/);
  expect(installRequest?.body).toEqual({
    cloud_name: 'Npcink Validation Cloud',
    public_base_url: 'https://cloud.example.com',
    database: {
      host: 'pgm-private.pg.rds.aliyuncs.com',
      port: 5432,
      database: 'npcink_cloud',
      username: 'npcink_app',
      password: databasePassword,
      ssl_mode: 'verify-full',
      ca_pem: '-----BEGIN CERTIFICATE-----\nTEST-ONLY\n-----END CERTIFICATE-----',
    },
  });

  const storageAfterInstall = await page.evaluate(() => ({
    local: JSON.stringify(window.localStorage),
    session: JSON.stringify(window.sessionStorage),
  }));
  expect(storageAfterInstall.local).not.toContain(adminKey);
  expect(storageAfterInstall.session).not.toContain(adminKey);
});
