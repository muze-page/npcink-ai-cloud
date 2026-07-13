import { expect, test, type Page } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

type Pack = {
  pack_id: string;
  label: string;
  ai_credits: number;
  amount: number;
  currency: string;
  recommended_for_tiers: string[];
  validity_days: number;
  active: boolean;
};

const initialPacks: Pack[] = [
  { pack_id: 'pack_small', label: 'Small credit pack', ai_credits: 10000, amount: 9.9, currency: 'CNY', recommended_for_tiers: ['free', 'plus'], validity_days: 365, active: true },
  { pack_id: 'pack_medium', label: 'Medium credit pack', ai_credits: 35000, amount: 19.9, currency: 'CNY', recommended_for_tiers: ['pro', 'agency'], validity_days: 365, active: true },
  { pack_id: 'pack_large', label: 'Large credit pack', ai_credits: 150000, amount: 99, currency: 'CNY', recommended_for_tiers: ['agency'], validity_days: 365, active: false },
];

async function installCreditPackHarness(page: Page) {
  await installAdminMocks(page);
  let items = initialPacks.map((item) => ({ ...item, recommended_for_tiers: [...item.recommended_for_tiers] }));
  let getCount = 0;
  let patchCount = 0;
  let lastPatch: Pack[] = [];
  let failNextGet = false;
  await page.route('**/api/admin/credit-packs', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      getCount += 1;
      if (failNextGet) {
        failNextGet = false;
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ status: 'error', message: 'temporary catalog failure' }) });
        return;
      }
    } else if (method === 'PATCH') {
      patchCount += 1;
      const body = route.request().postDataJSON() as { items?: Pack[] };
      lastPatch = Array.isArray(body.items) ? body.items : [];
      items = lastPatch.map((item) => ({ ...item, currency: 'CNY' }));
    } else {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        data: {
          catalog_version: 'credit_pack_catalog_v1',
          period_policy: 'payment_order_grant',
          expiry_policy: 'paid_at_plus_validity_days',
          default_validity_days: 365,
          updated_at: '2026-07-12T08:00:00Z',
          items,
        },
      }),
    });
  });
  return {
    getGetCount: () => getCount,
    getPatchCount: () => patchCount,
    getLastPatch: () => lastPatch,
    failNextRequest: () => { failNextGet = true; },
  };
}

test('credit pack directory is read-first, URL-backed, retained on refresh failure, and mobile safe', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installCreditPackHarness(page);
  await page.goto('/admin/credit-packs');

  await expect(page.locator('[data-ui="credit-pack-directory-item"]')).toHaveCount(3);
  await expect(page.locator('main input')).toHaveCount(0);
  await expect(page.locator('#credit-pack-inspector')).toContainText('Small credit pack');
  expect(harness.getGetCount()).toBe(1);

  await page.locator('[data-pack-id="pack_medium"] button').click();
  await expect(page).toHaveURL(/focus=pack_medium/);
  await expect(page.locator('#credit-pack-inspector')).toContainText('Medium credit pack');
  await page.reload();
  await expect(page.locator('[data-pack-id="pack_medium"] button')).toHaveAttribute('aria-pressed', 'true');

  await page.getByRole('button', { name: /^Inactive$|^未启用$|^未啟用$/i }).click();
  await expect(page).toHaveURL(/status=inactive/);
  await expect(page.locator('[data-ui="credit-pack-directory-item"]')).toHaveCount(1);
  await expect(page.locator('#credit-pack-inspector')).toContainText('Large credit pack');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(await page.locator('[data-ui="credit-pack-directory-item"]').evaluate((element) => element.getBoundingClientRect().top)).toBeLessThan(650);

  harness.failNextRequest();
  await page.getByRole('button', { name: /^Refresh$|^刷新$/i }).click();
  await expect(page.getByText(/last successfully loaded credit pack catalog|最近一次成功加载的积分包目录/i)).toBeVisible();
  await expect(page.locator('[data-pack-id="pack_large"]')).toBeVisible();
});

test('credit pack editor changes one selected pack while preserving the atomic catalog payload', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const harness = await installCreditPackHarness(page);
  await page.goto('/admin/credit-packs?focus=pack_medium');

  await page.getByRole('button', { name: /Edit selected pack|编辑当前积分包/i }).click();
  let editor = page.getByRole('dialog', { name: /Edit Medium credit pack|编辑 Medium credit pack/i });
  await expect(editor.getByRole('button', { name: /Save pack|保存积分包/i })).toBeDisabled();
  await editor.getByRole('button', { name: /^Cancel$|^取消$/i }).click();
  expect(harness.getPatchCount()).toBe(0);

  await page.getByRole('button', { name: /Edit selected pack|编辑当前积分包/i }).click();
  editor = page.getByRole('dialog', { name: /Edit Medium credit pack|编辑 Medium credit pack/i });
  await editor.getByLabel(/^Amount|^价格/i).fill('29.9');
  await editor.getByRole('button', { name: /Save pack|保存积分包/i }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByText(/Credit pack catalog saved|积分包目录已保存/i)).toBeVisible();
  expect(harness.getPatchCount()).toBe(1);
  expect(harness.getLastPatch()).toHaveLength(3);
  expect(harness.getLastPatch().find((item) => item.pack_id === 'pack_medium')?.amount).toBe(29.9);
  expect(harness.getLastPatch().find((item) => item.pack_id === 'pack_small')?.amount).toBe(9.9);
  await expect(page.locator('#credit-pack-inspector')).toContainText('29.90');
});
