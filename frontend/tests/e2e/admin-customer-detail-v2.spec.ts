import { expect, test } from '@playwright/test';
import { LONG_ACCOUNT_ID, installAdminMocks } from './helpers/admin-operator-fixture';

test('customer detail v2 keeps governed commercial and audited credit operations in their task tabs', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(
    page.getByRole('heading', { name: /Npcink AI Demo|MVP Account|acct_mvp_enterprise_primary/i }).first()
  ).toBeVisible();
  await expect(page.getByRole('tab', { name: /^Overview|^概况|^概況/i })).toHaveAttribute('aria-selected', 'true');

  await page.getByRole('tab', { name: /Commercial|商业与套餐|商業與方案/i }).click();
  await page.getByRole('button', { name: /^Free/i }).first().click();
  const packageDialog = page.getByRole('dialog');
  await expect(packageDialog).toContainText(/Confirm package change|确认更换套餐|確認更換方案/i);
  await packageDialog.getByRole('button', { name: /Change package|更换套餐|更換方案/i }).click();
  await expect(page.getByRole('button', { name: /Free.*Current|Free.*当前|Free.*目前/i }).first()).toBeVisible();

  await page.getByRole('tab', { name: /Audit|审计|稽核/i }).click();
  await expect(page.getByText('account.subscription.change')).toBeVisible();

  await page.getByRole('tab', { name: /Credits and usage|积分与用量|積分與用量/i }).click();
  await page.getByLabel(/Credit delta|积分变动|積分變動/i).fill('250');
  await page.getByLabel(/^Reason$|^原因$/i).fill('e2e governed adjustment');
  await page.getByRole('button', { name: /Apply adjustment|应用调整|套用調整/i }).click();
  await expect(page.getByLabel(/Credit delta|积分变动|積分變動/i)).toHaveValue('');

  await page.getByRole('tab', { name: /Audit|审计|稽核/i }).click();
  await expect(page.getByText('account.credit.adjustment')).toBeVisible();
});

test('customer detail failure preserves the PC shell and bounded retry', async ({ page }) => {
  await installAdminMocks(page);
  await page.unroute('**/api/admin/**');
  let attempts = 0;
  await page.route(`**/api/admin/accounts/${LONG_ACCOUNT_ID}`, async (route) => {
    attempts += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'error', message: 'customer unavailable' }),
    });
  });
  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);

  await expect(page.getByRole('heading', { name: /Customer detail is temporarily unavailable|客户详情暂时不可用/i })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: /Failed to load|加载数据失败/i })).toBeVisible();
  await page.getByRole('button', { name: /^Retry$|^重试$/i }).click();
  await expect.poll(() => attempts).toBe(2);
  await expect(page).toHaveURL(new RegExp(`/admin/accounts/${LONG_ACCOUNT_ID}$`));
});
