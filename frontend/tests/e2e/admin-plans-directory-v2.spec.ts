import { expect, test, type Page } from '@playwright/test';
import { buildAdminApiErrorEnvelope, installAdminMocks } from './helpers/admin-operator-fixture';

async function installPlanDirectoryHarness(page: Page) {
  await installAdminMocks(page);
  let requestCount = 0;
  let failNext = false;
  await page.route('**/api/admin/plans', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    requestCount += 1;
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify(buildAdminApiErrorEnvelope('temporary package catalog failure')) });
      return;
    }
    await route.fallback();
  });
  return { getRequestCount: () => requestCount, failNextRequest: () => { failNext = true; } };
}

test('package directory keeps filters and focus while retaining the catalog on refresh failure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installPlanDirectoryHarness(page);
  await page.goto('/admin/plans');

  await expect(page.getByRole('heading', { name: /Standard package catalog|标准套餐目录/i })).toBeVisible();
  await expect(page.locator('[data-ui="plan-catalog-item"]')).toHaveCount(4);
  expect(harness.getRequestCount()).toBe(1);

  const rows = page.locator('[data-ui="plan-catalog-item"]');
  await expect(rows.nth(0)).toContainText('Plus');
  await expect(rows.nth(1)).toContainText('Agency');
  await expect(rows.nth(2)).toContainText('Free');
  await expect(page.locator('#plan-catalog-inspector')).toContainText('Plus');

  await page.getByRole('button', { name: /^Missing$|^缺失$/i }).click();
  await expect(page).toHaveURL(/state=missing/);
  await expect(rows).toHaveCount(2);

  await page.getByLabel(/Search packages|搜索套餐/i).fill('Plus');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/q=Plus/);
  await expect(rows).toHaveCount(1);

  const inspect = page.getByRole('button', { name: /^Inspect$|^检查$/i });
  await inspect.focus();
  await inspect.press('Enter');
  await expect(page).toHaveURL(/focus=plus/);
  await page.reload();
  await expect(page.getByLabel(/Search packages|搜索套餐/i)).toHaveValue('Plus');
  await expect(page.locator('#plan-catalog-inspector')).toContainText('Plus');

  harness.failNextRequest();
  await page.getByRole('button', { name: /Refresh catalog|刷新目录/i }).click();
  await expect(page.getByText(/last successfully loaded catalog|最近一次成功加载的套餐目录/i)).toBeVisible();
  await expect(rows).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('package inspector opens bounded detail while creation stays in advanced maintenance', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installPlanDirectoryHarness(page);
  await page.goto('/admin/plans');

  await expect(page.getByRole('heading', { name: /Create package record|创建套餐记录/i })).toHaveCount(0);
  const freeRow = page.locator('[data-ui="plan-catalog-item"]').filter({ hasText: 'Free' });
  await freeRow.getByRole('button', { name: /^Inspect$|^检查$/i }).click();
  const inspector = page.locator('#plan-catalog-inspector');
  await expect(page).toHaveURL(/focus=free/);
  await expect(inspector.getByRole('link', { name: /^Details$|^详情$/i })).toHaveAttribute('href', '/admin/plans/free');
  await expect(inspector.getByRole('link', { name: /Open subscriptions|打开订阅/i })).toHaveAttribute('href', '/admin/subscriptions?plan_id=free');

  await page.getByText(/Package initialization|套餐初始化/i).click();
  await expect(page.getByRole('heading', { name: /Create package record|创建套餐记录/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Create missing packages|创建缺失套餐|补齐缺失套餐/i })).toBeVisible();
});
