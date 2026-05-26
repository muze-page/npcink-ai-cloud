import { expect, test, type Locator } from '@playwright/test';
import { FREE_PLAN_ID, LONG_ACCOUNT_ID, LONG_PLAN_ID, LONG_RECOGNITION_MODEL_ID, installAdminMocks } from './helpers/admin-operator-fixture';

async function setScopedInputValue(scope: Locator, index: number, value: string) {
  await scope.locator('input.input').nth(index).evaluate((element, nextValue) => {
    const input = element as HTMLInputElement;
    input.focus();
    input.value = String(nextValue);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.blur();
  }, value);
}

async function replaceScopedTextInput(scope: Locator, index: number, value: string) {
  const input = scope.locator('input.input').nth(index);
  await input.click({ force: true });
  await input.press(`${process.platform === 'darwin' ? 'Meta' : 'Control'}+A`);
  await input.pressSequentially(value);
}

test('admin operator path smoke: queue and inspector routes stay connected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin');
  await expect(page.getByText(/加载中\.\.\./)).not.toBeVisible();
  await expect(page.getByRole('heading', { name: /Platform state comes first|先看平台概况/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Review coverage|检查覆盖|檢查覆蓋/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer coverage|打开客户覆盖|打開客戶覆蓋/i }).first()).toBeVisible();

  await page.goto('/admin/coverage');
  await expect(page.getByRole('heading', { name: /Customer coverage|客户覆盖|客戶覆蓋/i })).toBeVisible();
  await expect(page.getByText(/Customers needing coverage follow-up|需要覆盖跟进的客户|需要覆蓋跟進的客戶/i).first()).toBeVisible();
  await expect(page.getByText(/Subscription risks|订阅风险|訂閱風險/i).first()).toBeVisible();
  await expect(page.getByText(/Sites needing follow-up|需要跟进的站点|需要跟進的站點/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer|打开客户|打開客戶/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Inspect detail|查看详情|檢查詳情/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open package catalog|打开套餐目录|打開方案目錄/i })).toHaveCount(1);
  await expect(page.getByRole('button', { name: /Open package catalog|打开套餐目录|打開方案目錄/i })).toHaveCount(0);

  await page.goto('/admin/subscriptions');
  await expect(page.getByRole('heading', { name: /Risk-prioritized subscription queue|按风险排序的订阅队列/i })).toBeVisible();
  await expect(page.locator('a[href="/admin/subscriptions/sub_mvp"]')).toBeVisible();
  await expect(page.getByText(/Snapshot follow-up|快照跟进/i).first()).toBeVisible();
  await expect(page.getByText(/Billing snapshot fresh|账单快照最新|账单快照新鲜/i).first()).toBeVisible();

  await page.goto('/admin/subscriptions/sub_mvp');
  await expect(page.getByRole('heading', { name: /Coverage detail: sub_mvp|覆盖详情：sub_mvp|覆蓋詳情：sub_mvp/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Inspect customer detail|检查客户详情|檢查客戶詳情/i })).toBeVisible();
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();
  await expect(page.getByText(/Base budget|基础预算/i).first()).toBeVisible();
  await expect(page.getByText(/Effective budget|有效预算/i).first()).toBeVisible();
  await expect(page.getByText(/Snapshot freshness|快照新鲜度/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Rebuild current-period billing snapshots|重建当前周期账单快照/i })).toHaveCount(0);
  await expect(page.getByText(/checkout|buy points|storefront/i)).toHaveCount(0);

  await page.goto('/admin/impersonations');
  await expect(
    page.getByRole('heading', { name: /An active impersonation session needs bounded follow-up|当前存在需要收口的模拟登录会话/i })
  ).toBeVisible();
  await expect(page.getByText(/imp_active_p\.\.\.ession/i).first()).toBeVisible();

  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(page.getByRole('heading', { name: /MVP Account|acct_mvp_enterprise_primary/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.getByText(/Operator actions|运营动作|營運動作/i).first()).toBeVisible();
  await expect(page.getByText(/View member coverage details|查看成员覆盖详情|檢視成員覆蓋詳情/i).first()).toBeVisible();

  await page.goto('/admin/members');
  await expect(page.getByRole('heading', { name: /Support access queue|支持访问队列/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /All members|全部成员/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Coverage risks|覆盖风险/i })).toBeVisible();
  await expect(page.getByText(/Product role|产品角色/i).first()).toBeVisible();
  await expect(page.getByText(/User Admin|用户管理员|使用者管理員/i).first()).toBeVisible();
  await expect(page.getByText(/Coverage follow-up required|需要覆盖跟进|覆盖跟进/i).first()).toBeVisible();
  await expect(page.getByText(/Dev baseline|开发基线/i).first()).toBeVisible();
  await expect(page.getByText(/Disabled mapping|禁用映射/i).first()).toBeVisible();
  await expect(page.locator('a[href="/admin/accounts/acct_mvp_enterprise_primary"]').first()).toBeVisible();
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();
  await expect(page.locator('a[href="/admin/subscriptions/sub_growth"]').first()).toBeVisible();
  await expect(
    page.locator('a[href="/admin/impersonations?account_id=acct_mvp_enterprise_primary&member_ref=user%3Aadmin%40example.com&site_id=site_mvp"]').first()
  ).toBeVisible();

  await page.getByRole('button', { name: /Pending access cleanup|待清理访问/i }).click();
  await expect(page).toHaveURL(/view=pending_cleanup/);

  await page.goto('/admin/sites', { waitUntil: 'domcontentloaded' });
  await expect(
    page.getByRole('heading', { name: /Which sites need operator follow-up next\?|哪些站点需要下一步运营跟进？/i })
  ).toBeVisible();
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();

  await page.goto('/admin/sites/site_mvp');
  await expect(page.getByRole('heading', { name: /MVP Site|site_mvp/i }).first()).toBeVisible();

  await page.goto('/admin/plans', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Coverage package catalog|覆盖套餐目录|覆蓋方案目錄/i })).toBeVisible();
  await expect(page.getByText(/Default production plans|默认生产套餐|預設生產方案/i).first()).toBeVisible();
  await page.getByText(/Inspect canonical package shell maintenance|查看套餐模板维护|查看方案模板維護/i).click();
  await expect(page.locator(`a[href="/admin/plans/${FREE_PLAN_ID}"]`)).toBeVisible();
  await expect(page.getByText(/基础版|Basic/i).first()).toBeVisible();
  await expect(page.getByText(/批量版|Bulk/i).first()).toBeVisible();
  await expect(page.getByText(/Site limit|站点上限/i).first()).toBeVisible();
  await expect(page.locator(`a[href="/admin/plans/${LONG_PLAN_ID}"]`)).toBeVisible();
  await expect(page.getByText(/checkout|buy points|storefront/i)).toHaveCount(0);

  await page.goto(`/admin/plans/${LONG_PLAN_ID}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Basic|套餐详情/i }).first()).toBeVisible();
  await expect(page.getByText(/plan_basic_primary/i).first()).toBeVisible();
  await expect(page.getByText(/Site limit|站点上限/i).first()).toBeVisible();
  await expect(page.getByText(/Structured package fields|结构化套餐字段/i)).toBeVisible();
  await expect(page.getByText(/Advanced JSON overrides|高级 JSON 覆盖项/i)).toBeVisible();
});

test('admin queue pages keep one primary header action and shared identifier treatment', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/subscriptions');
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();

  await page.goto('/admin/sites');
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();

  await page.goto('/admin/accounts');
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toBeVisible();
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /Open coverage|打开覆盖|打開覆蓋|检查覆盖|檢查覆蓋/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Review coverage|检查覆盖|檢查覆蓋/i }).first()).toBeVisible();
  await page.getByLabel(/Package kind|套餐类型|方案類型/i).selectOption('formal_free');
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toBeVisible();
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toHaveCount(0);
  await page.getByLabel(/Package kind|套餐类型|方案類型/i).selectOption('');
  await page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i).selectOption('uncovered');
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toBeVisible();
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toHaveCount(0);
  await page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i).selectOption('');
  await page.getByLabel(/Account ID|账户 ID|帳戶 ID/i).fill('acct_new_customer_free');
  await page.getByLabel(/Name|名称|名稱/i).fill('New Customer');
  await page.getByRole('button', { name: /Create customer account|创建客户账号|建立客戶帳號/i }).click();
  await expect(page.getByText(/bound to the Free package|绑定 Free 套餐|綁定 Free 方案/i)).toBeVisible();

  await page.goto('/admin/plans', { waitUntil: 'domcontentloaded' });
  await expect(page.locator(`a[href="/admin/plans/${LONG_PLAN_ID}"]`).first()).toBeVisible();
  await page.goto(`/admin/plans/${LONG_PLAN_ID}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText(/plan_basic_primary/i).first()).toBeVisible();
  await expect(page.getByText(/Package fit is stable|套餐匹配稳定/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Apply .* baseline/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Reset to latest release|恢复为最新发布记录|恢復為最新發佈記錄/i })).toBeVisible();
  await expect(page.getByText(/已发布|published/i).first()).toBeVisible();
});

test('admin model intelligence stays a bounded internal review page', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto(`/admin/model-intelligence?model_id=${LONG_RECOGNITION_MODEL_ID}`);
  await expect(page.getByRole('heading', { level: 1, name: /Model intelligence|模型情报|模型情報/i })).toBeVisible();
  await expect(page.getByText(/Source repair bridge|修源桥接|修源橋接/i)).toBeVisible();
  await expect(page.getByText('model_demo_e...rimary').first()).toBeVisible();
  await expect(page.locator('[data-ui="backoffice-status-badge"]').first()).toBeVisible();
  await expect(page.locator('[data-ui="admin-semantic-badge"]').first()).toBeVisible();
  await expect(page.locator('[data-ui="backoffice-filter-pill"]').first()).toBeVisible();
});

test('admin recognition path stays compatibility-only and redirects to model intelligence', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto(`/admin/recognition?model_id=${LONG_RECOGNITION_MODEL_ID}`);
  await page.waitForURL(new RegExp(`/admin/model-intelligence\\?(?:.*&)?model_id=${LONG_RECOGNITION_MODEL_ID}$`));
  await expect(page.getByRole('heading', { level: 1, name: /Model intelligence|模型情报|模型情報/i })).toBeVisible();
});

test('admin support and detail pages keep bounded operator hierarchy', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/impersonations');
  await expect(page.getByText(/imp_active_p\.\.\.ession/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /End impersonation|结束模拟会话|结束模拟登录/i }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Start impersonation|发起模拟会话/i })).toHaveCount(0);
  await expect(
    page.getByText(/Start a new impersonation only after the active session is closed|先结束当前会话后再开始新的模拟登录/i)
  ).toBeVisible();
  await expect(page.locator('table').getByText('acct_mvp_ent...rimary').first()).toBeVisible();

  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.getByText(/Operator actions|运营动作|營運動作/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /Open coverage|打开覆盖|打開覆蓋/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /View sites|查看站点|檢視站點/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Invite member|邀请成员|邀請成員/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Start impersonation|发起模拟会话|發起模擬會話/i })).toBeVisible();
  await expect(page.getByText(/Manage support session|管理支持会话|管理支援工作階段/i).first()).toBeVisible();
  await expect(page.getByText(/Manage portal access|管理成员接入|管理 Portal 存取/i).first()).toBeVisible();
  await expect(page.getByLabel(/Plan Version|套餐版本|方案版本/i)).toBeHidden();
  await expect(page.getByLabel(/Email|邮箱|電子郵件/i)).toBeHidden();
  const advancedCoverageControls = page.locator('[data-ui="advanced-coverage-controls"]');
  const memberCoverageDetails = page.locator('[data-ui="member-coverage-details"]');
  await expect(advancedCoverageControls).toHaveJSProperty('open', false);
  await expect(memberCoverageDetails).toHaveJSProperty('open', false);
  await expect(advancedCoverageControls.getByRole('link', { name: /Inspect detail|查看详情|檢查詳情/i })).toBeHidden();
  await expect(advancedCoverageControls.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i })).toBeHidden();
  const packageActionReveal = page.getByText(/Advanced coverage controls|高级覆盖控制|進階覆蓋控制/i);
  await packageActionReveal.click();
  await expect(advancedCoverageControls).toHaveJSProperty('open', true);
  const coverageBoundary = page.locator('#coverage-actions');
  await expect(advancedCoverageControls.getByRole('link', { name: /Inspect detail|查看详情|檢查詳情/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Change package|调整套餐|調整方案/i })).toBeVisible();
  await expect(page.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i })).toBeVisible();
  await expect(page.getByRole('textbox', { name: /Coverage package version|覆盖套餐版本|覆蓋方案版本/i })).toHaveCount(0);
  await expect(page.getByText(/applied automatically|自动应用|自動套用/i).first()).toBeVisible();
  await page.getByRole('button', { name: /Suspend coverage|暂停覆盖|暫停覆蓋/i }).click();
  await expect(coverageBoundary.getByText(/已暂停|suspended/i).first()).toBeVisible();
  await packageActionReveal.click();
  await page.getByRole('button', { name: /Cancel coverage|取消覆盖|取消覆蓋/i }).click();
  await expect(coverageBoundary.getByText(/已取消|canceled/i).first()).toBeVisible();
  await packageActionReveal.click();
  await page.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i }).selectOption(LONG_PLAN_ID);
  await page.getByRole('button', { name: /Change package|调整套餐|調整方案/i }).click();
  await expect(coverageBoundary.getByText(/Basic/i).first()).toBeVisible();
  await expect(page.getByText(/Covered by paid package|付费套餐已覆盖|付費方案已覆蓋/i).first()).toBeVisible();
  await expect(page.getByText(/admin@example\.com/i).first()).toBeVisible();
  await expect(page.getByText(/View member coverage details|查看成员覆盖详情|檢視成員覆蓋詳情/i).first()).toBeVisible();
  await expect(memberCoverageDetails).toHaveJSProperty('open', false);
  await expect(page.getByText(/Portal access|成员接入|Portal 存取/i).first()).toBeVisible();
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();

  await page.goto('/admin/sites/site_mvp');
  await expect(page.getByText('site_mvp').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open coverage|打开覆盖|打開覆蓋/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Inspect subscription detail|查看订阅详情|檢查訂閱詳情/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /View audit trail|查看审计/i }).first()).toBeVisible();
  await page.getByText(/Inspect audit follow-up|查看审计跟进|查看稽核跟進/i).click();
  await expect(page.getByText(/Recent audit summary for this site|此站点的近期审计摘要/i)).toBeVisible();
  await expect(page.getByText(/subscription\.bind|provider_connection\.sync/i).first()).toBeVisible();

  await page.goto('/admin/subscriptions/sub_mvp');
  await expect(page.getByText('sub_mvp').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Customer|客户/i }).first()).toBeVisible();
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();
  await expect(page.getByText(/Covered sites|覆盖站点/i).first()).toBeVisible();
  await expect(page.getByText(/Coverage checks|覆盖检查|覆蓋檢查/i).first()).toBeVisible();
  await expect(page.getByText(/Snapshot freshness|快照新鲜度|快照新鮮度/i).first()).toBeVisible();
  await expect(page.getByText(/current-period integrity|当前周期完整性|當前週期完整性/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /View audit trail|查看审计/i }).first()).toBeVisible();
  await expect(page.getByText(/Recent audit summary for this subscription|此订阅的近期审计摘要/i)).toBeVisible();
});

test('admin mutation receipts keep bounded audit backlink filters', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/impersonations');
  await page
    .locator('table')
    .getByRole('button', { name: /End impersonation|结束模拟会话|结束模拟登录/i })
    .first()
    .click({ force: true });

  await expect(page.getByText(/Impersonation ended|模拟会话已结束/i)).toBeVisible();
  await expect(page.getByText(/Latest receipt|最新回执/i)).toBeVisible();
  await expect(
    page.getByText(/Read-only impersonation .* is now ended\./i)
  ).toBeVisible();
  await expect(page.getByText(/platform_impersonation\.end/i).first()).toBeVisible();
  await expect(
    page.locator('a[href*="/api/admin/audit-events?"]').filter({
      hasText: /View audit trail|查看审计/i,
    }).first()
  ).toHaveAttribute(
    'href',
    /\/api\/admin\/audit-events\?(?:.*&)?account_id=acct_mvp_enterprise_primary(?:&.*)?site_id=site_mvp(?:&.*)?event_kind=platform_impersonation\.end(?:&.*)?outcome=succeeded/
  );
});

test('admin navigation stays customer-first', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin');

  const adminNav = page.getByRole('navigation', { name: /管理后台|admin/i });
  const adminPrimaryNav = page.locator('[data-ui="admin-primary-nav"]');
  await expect(adminPrimaryNav.locator('> a.admin-nav-link')).toHaveCount(4);
  await expect(adminNav.getByRole('link', { name: /^Overview$|^概览$|^概覽$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Customers$|^客户$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Sites$|^站点$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Coverage$|^覆盖$|^覆蓋$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Subscriptions$|^订阅$|^訂閱$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Plans$|^套餐目录$|^方案目錄$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Members$|^成员$|^成員$/i })).toHaveCount(0);
});
