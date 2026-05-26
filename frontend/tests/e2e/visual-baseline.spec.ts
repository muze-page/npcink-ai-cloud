/**
 * Cloud Frontend Visual Baseline Tests
 * 
 * 覆盖范围：
 * - Marketing: /(marketing)/getting-started 页面
 * - Portal: /portal 主页面
 * - Portal Billing: /portal/billing 页面
 * - Admin: /admin 管理后台
 * 
 * 注意：这些测试需要运行在开发或生产环境中，并且需要适当的认证状态。
 * 对于需要登录的页面，测试会使用固定测试数据或预置认证状态。
 */
import { expect, test } from '@playwright/test';

/**
 * Getting Started 页面视觉基线
 * 验证：Hero 区、步骤卡片、FAQ、CTA
 */
test('cloud frontend visual baseline: getting started page', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/getting-started');

  // 验证关键元素
  await expect(
    page.getByText(
      /Current routes cover hosted runtime onboarding|现有路由覆盖 hosted runtime 接入|現有路由涵蓋 hosted runtime 接入/i
    )
  ).toBeVisible();

  await expect(
    page.getByRole('heading').first()
  ).toBeVisible();

  // 等待页面完全加载
  await page.waitForLoadState('networkidle');

  // 截取整个页面
  await expect(page).toHaveScreenshot('getting-started-baseline.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });

  // 截取 Hero 区
  const heroSection = page.locator('section').first();
  if (await heroSection.isVisible()) {
    await expect(heroSection).toHaveScreenshot('getting-started-hero.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }

  // 截取步骤卡片
  const stepsSection = page.locator('section').nth(1);
  if (await stepsSection.isVisible()) {
    await expect(stepsSection).toHaveScreenshot('getting-started-steps.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }

  // 截取 FAQ 区
  const faqSection = page.locator('section').nth(2);
  if (await faqSection.isVisible()) {
    await expect(faqSection).toHaveScreenshot('getting-started-faq.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }
});

/**
 * Portal 主页面视觉基线
 * 验证：成员访问状态、站点列表、预览上下文
 */
test('cloud frontend visual baseline: portal page', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/portal');

  // 等待页面加载
  await page.waitForLoadState('networkidle');

  // 处理未登录状态 - 显示登录提示
  const notSignedIn = page.getByText(/not signed in|please sign in|未登录/i).first();
  if (await notSignedIn.isVisible()) {
    // 截取未登录状态
    await expect(page).toHaveScreenshot('portal-not-authenticated.png', {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
    return;
  }

  // 验证已登录状态的关键元素
  await expect(
    page.getByText(/Member-Gated Preview|成员预览面/i).first()
  ).toBeVisible();

  // 截取整个页面
  await expect(page).toHaveScreenshot('portal-baseline.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });

  // 截取 Hero 区
  const heroSection = page.locator('section').first();
  if (await heroSection.isVisible()) {
    await expect(heroSection).toHaveScreenshot('portal-hero.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }

  // 截取站点列表
  const sitesSection = page.locator('section').nth(1);
  if (await sitesSection.isVisible()) {
    await expect(sitesSection).toHaveScreenshot('portal-sites-grid.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }
});

/**
 * Portal Billing 页面视觉基线
 * 验证：账单预览、对账信号、快照历史
 */
test('cloud frontend visual baseline: portal billing page', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/portal/billing');

  // 等待页面加载
  await page.waitForLoadState('networkidle');

  // 处理未登录状态
  const notSignedIn = page.getByText(/not signed in|please sign in|未登录/i).first();
  if (await notSignedIn.isVisible()) {
    await expect(page).toHaveScreenshot('billing-not-authenticated.png', {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
    return;
  }

  // 验证已登录状态的关键元素
  await expect(
    page.getByText(/Billing Preview|账单预览/i).first()
  ).toBeVisible();

  // 截取整个页面
  await expect(page).toHaveScreenshot('billing-baseline.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });

  // 截取对账面板
  const reconciliationSection = page.locator('section').nth(1);
  if (await reconciliationSection.isVisible()) {
    await expect(reconciliationSection).toHaveScreenshot('billing-reconciliation-panel.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }
});

/**
 * Admin 管理后台视觉基线
 * 验证：运营快照、服务健康、运行时信号、控制甲板
 */
test('cloud frontend visual baseline: admin page', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/admin');

  // 等待页面加载
  await page.waitForLoadState('networkidle');

  // 处理未授权状态
  const unauthorized = page.getByText(/unauthorized|access denied|未授权/i).first();
  if (await unauthorized.isVisible()) {
    await expect(page).toHaveScreenshot('admin-unauthorized.png', {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
    return;
  }

  // 处理内部登录门禁状态
  const internalOnlyGate = page
    .getByText(/Internal Only|仅内部使用|僅供內部使用/i)
    .first();
  if (await internalOnlyGate.isVisible()) {
    await expect(page).toHaveScreenshot('admin-login-gate.png', {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
    return;
  }

  // 验证关键元素
  await expect(
    page.getByText(/Operations Snapshot|运营快照|營運快照/i).first()
  ).toBeVisible();

  // 截取整个页面
  await expect(page).toHaveScreenshot('admin-baseline.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
    maxDiffPixelRatio: 0.02,
  });

  // 截取 Hero 区
  const heroSection = page.locator('section').first();
  if (await heroSection.isVisible()) {
    await expect(heroSection).toHaveScreenshot('admin-hero.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }

  // 截取服务健康面板
  const healthSection = page.locator('section').nth(1);
  if (await healthSection.isVisible()) {
    await expect(healthSection).toHaveScreenshot('admin-service-health.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }

  // 截取控制甲板
  const controlDeckSection = page.locator('section').last();
  if (await controlDeckSection.isVisible()) {
    await expect(controlDeckSection).toHaveScreenshot('admin-control-deck.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
  }
});
