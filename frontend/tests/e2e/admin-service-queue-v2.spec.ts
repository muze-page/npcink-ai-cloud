import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

test('service risk queue keeps filters and inspector focus in the URL on PC', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/coverage');
  await expect(page.getByRole('heading', { name: /^Service risk queue$|^服务风险队列$/i })).toBeVisible();
  await expect(page.locator('[data-ui="coverage-queue-item"]')).toHaveCount(2);
  await expect(page.locator('table')).toHaveCount(0);

  await page.getByRole('button', { name: /^(All|全部)\s*·\s*3$/i }).click();
  await expect(page.locator('[data-ui="coverage-queue-item"]')).toHaveCount(3);

  await page.getByLabel(/^Search$|^搜索$/i).fill('Uncovered');
  await expect(page.locator('[data-ui="coverage-queue-item"]')).toHaveCount(1);
  await expect(page.getByText('Uncovered Account').first()).toBeVisible();
  await expect(page).toHaveURL(/q=Uncovered/);

  await page.getByRole('combobox', { name: /Reason|原因/i }).selectOption('missing_package_coverage');
  await page.getByRole('combobox', { name: /Sort|排序/i }).selectOption('customer');
  const inspectButton = page.getByRole('button', { name: /^Inspect$|^检查$/i });
  await inspectButton.focus();
  await inspectButton.press('Enter');

  await expect(page).toHaveURL(/status=all/);
  await expect(page).toHaveURL(/q=Uncovered/);
  await expect(page).toHaveURL(/reason=missing_package_coverage/);
  await expect(page).toHaveURL(/sort=customer/);
  await expect(page).toHaveURL(/focus=acct_uncovered%3Amissing_package_coverage/);
  await expect(page.locator('#coverage-inspector')).toContainText('Uncovered Account');

  await page.reload();
  await expect(page.getByLabel(/^Search$|^搜索$/i)).toHaveValue('Uncovered');
  await expect(page.getByRole('combobox', { name: /Reason|原因/i })).toHaveValue('missing_package_coverage');
  await expect(page.getByRole('combobox', { name: /Sort|排序/i })).toHaveValue('customer');
  await expect(page.locator('[data-ui="coverage-queue-item"]')).toHaveCount(1);

  await page.route('**/api/admin/coverage-work-queue', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'error', message: 'temporary queue refresh failure' }),
    });
  });
  await page.getByRole('button', { name: /Refresh queue|刷新队列/i }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('[data-ui="coverage-queue-item"]')).toHaveCount(1);
  await expect(page.getByLabel(/^Search$|^搜索$/i)).toHaveValue('Uncovered');

});
