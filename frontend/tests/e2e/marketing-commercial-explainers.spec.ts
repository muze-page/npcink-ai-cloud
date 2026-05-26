import { expect, test } from '@playwright/test';

test('marketing commercial explainers stay request-only and non-transactional', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });

  await page.goto('/packages');
  await expect(
    page.getByRole('heading', {
      name: /Compare the current Cloud packages at a glance|一眼看懂当前 Cloud 套餐差异|一眼看懂目前的 Cloud 方案差異/i,
    })
  ).toBeVisible();
  await expect(page.locator('div').filter({ hasText: /^included points$/i })).toBeVisible();
  await expect(page.getByText(/10,000|50,000/).first()).toBeVisible();
  await expect(page.getByText(/Grace period|grace period/i).first()).toBeVisible();
  await expect(page.getByText(/Fail closed|fail closed/i).first()).toBeVisible();
  await expect(page.getByText(/How to choose|怎么选|怎麼選/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /Review current package posture|查看当前套餐状态|查看目前方案狀態/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Review top-up guidance|查看加量说明|查看加量說明/i }).first()).toBeVisible();
  await expect(page.getByText(/Ask an operator to review package fit|请 operator 评估套餐是否需要调整|請 operator 評估方案是否需要調整/i)).toBeVisible();
  await expect(page.getByText(/Buy now|Checkout|Wallet|Storefront/i)).toHaveCount(0);

  await page.goto('/top-up-packs');
  await expect(
    page.getByRole('heading', {
      name: /Use top-up packs as current-period headroom, not as a stored balance|把加量包理解为当前周期 headroom，而不是长期余额|把加量包理解為目前週期 headroom，而不是長期餘額/i,
    })
  ).toBeVisible();
  await expect(page.getByText(/Current-period only\?|只影响当前周期？|只影響目前週期？/i).first()).toBeVisible();
  await expect(page.getByText(/Rolls over\?|会滚存？|會滾存？/i).first()).toBeVisible();
  await expect(page.getByText(/Points equivalent|points equivalent/i).first()).toBeVisible();
  await expect(page.getByText(/10,000|35,000|150,000/).first()).toBeVisible();
  await expect(page.getByText(/FAQ|常见问题|常見問題/i)).toBeVisible();
  await expect(page.getByText(/No|否/).first()).toBeVisible();
  await expect(page.getByText(/When to request top-up first|什么时候优先申请加量包|什麼時候優先申請加量包/i)).toBeVisible();
  await expect(
    page.getByText(
      /Ask an operator to review whether current-period top-up fits better than a package move|请 operator 评估当前周期加量是否比直接改套餐更合适|請 operator 評估目前週期加量是否比直接改方案更合適/i
    )
  ).toBeVisible();
  await expect(page.getByText(/Buy now|Checkout|Wallet|Storefront/i)).toHaveCount(0);
});
