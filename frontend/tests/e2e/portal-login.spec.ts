import { expect, test } from '@playwright/test';

test('portal login visual smoke: form renders unauthenticated state', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/portal/login');

  await expect(
    page.getByRole('heading', {
      name: /Welcome Back/i,
    })
  ).toBeVisible();

  await expect(
    page.getByLabel(/Email Address/i)
  ).toBeVisible();

  await expect(
    page.getByRole('button', {
      name: /Send Magic Link/i,
    })
  ).toBeVisible();

  await expect(page).toHaveScreenshot('portal-login.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });
});
