import { expect, test } from '@playwright/test';

test('marketing home visual smoke: hero and CTA render', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');

  await expect(
    page.getByRole('heading', {
      name: /Hosted AI Runtime for Modern Applications|面向现代应用的托管式 AI Runtime|面向現代應用的託管式 AI Runtime/i,
    })
  ).toBeVisible();

  await expect(
    page.getByRole('link', {
      name: /Get Started|开始使用|開始使用/i,
    })
  ).toBeVisible();

  await expect(
    page.getByRole('link', {
      name: /Sign In|登录|登入/i,
    }).first()
  ).toBeVisible();

  await expect(page).toHaveScreenshot('marketing-home.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });
});
