import { expect, test } from '@playwright/test';
import { installAdminMocks } from './helpers/admin-operator-fixture';

test('package editor contains PC keyboard focus and restores the invoking action', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await installAdminMocks(page);
  await page.goto('/admin/plans/pro');

  const editButton = page.getByRole('button', { name: /Edit package values|编辑套餐值/i });
  await editButton.click();
  const editor = page.getByRole('dialog', { name: /Edit current package values|编辑当前套餐值/i });
  await expect(editor).toBeVisible();
  await expect(editor.getByText(/Structured package fields|结构化套餐字段/i)).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(editor).toHaveCount(0);
  await expect(editButton).toBeFocused();
});
