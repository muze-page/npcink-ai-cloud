import { expect, test } from '@playwright/test';

test('marketing home visual smoke: hero and CTA render', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');

  await expect(
    page.getByRole('heading', {
      name: /Run AI.*cloud.*control.*site|让 AI.*云端.*控制权.*站点/i,
    })
  ).toBeVisible();

  await expect(
    page.getByRole('link', {
      name: /Start free|免费开始/i,
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
