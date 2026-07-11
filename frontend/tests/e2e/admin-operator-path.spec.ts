import { expect, test, type Locator } from '@playwright/test';
import { FREE_PLAN_ID, LONG_ACCOUNT_ID, LONG_PLAN_ID, installAdminMocks } from './helpers/admin-operator-fixture';

test('admin login validates the session before redirecting or showing the token form', async ({ page }) => {
  await installAdminMocks(page);

  await page.goto('/admin/login?redirect=/admin/plans');
  await expect(page).toHaveURL(/\/admin\/plans$/);
  await expect(page.locator('[data-ui="admin-primary-nav"]')).toBeVisible();
});

test('an invalid admin cookie does not expose navigation or trap the login page', async ({ page }) => {
  await page.route('**/admin/session', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'error',
        error_code: 'auth.admin_session_invalid',
        message: 'admin session is invalid',
      }),
    });
  });
  await page.goto('/admin/login');
  await page.context().addCookies([
    {
      name: 'npcink_admin_session_token',
      value: 'stale-admin-session',
      url: new URL(page.url()).origin,
    },
  ]);
  await page.reload();

  await expect(page.locator('#token')).toBeVisible();
  await expect(page.locator('[data-ui="admin-primary-nav"]')).toHaveCount(0);
});

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

test('admin coverage page keeps service queue primary and package catalog separate', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/coverage');
  await expect(page.getByRole('heading', { name: /^Customer service workspace$|^客户服务工作区$|^客戶服務工作區$/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Service status|Follow-up queue|服务状态|跟进队列|服務狀態|跟進隊列/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Packages|^Package overview|^套餐|^方案/i })).toHaveCount(0);
  await expect(page.getByText(/Customers needing service follow-up|需要服务跟进的客户|需要服務跟進的客戶/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Inspect subscription|查看订阅|檢查訂閱/i }).first()).toBeVisible();

  await expect(page.locator('a[href="/admin/plans"]').first()).toBeVisible();
});

test('admin subscription detail keeps localized operator layout', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/subscriptions/sub_mvp');
  await expect(page.getByRole('heading', { name: /Service status detail: Pro|服务状态详情：Pro|服務狀態詳情：Pro/i })).toBeVisible();
  await expect(page.getByText(/Package, usage, and service coverage|套餐、用量与服务覆盖|方案、用量與服務覆蓋/i).first()).toBeVisible();
  await expect(page.getByText(/What needs operator action|需要运营处理什么|需要營運處理什麼/i).first()).toBeVisible();
  await expect(page.getByText(/Related evidence|关联证据|關聯證據/i).first()).toBeVisible();
  await expect(page.getByText(/Coverage checks/i)).toHaveCount(0);
});

test('admin operator path smoke: queue and inspector routes stay connected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin');
  await expect(page.getByText(/加载中\.\.\./)).not.toBeVisible();
  await expect(page.getByRole('heading', { name: /Platform state comes first|先看平台概况/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Review service status|检查服务状态|檢查服務狀態/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer service status|打开客户服务状态|打開客戶服務狀態/i }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: /Which runtime signals need follow-up\?|哪些运行时状态需要继续跟进|哪些執行時狀態需要繼續跟進/i })).toBeVisible();
  await expect(
    page
      .getByText(/Provider call coverage gap|提供方调用遥测覆盖缺口|提供方呼叫遙測覆蓋缺口/i)
      .first()
  ).toBeVisible();
  await expect(
    page.locator('p', {
      hasText:
        /Provider call coverage gap|提供方调用遥测覆盖缺口|提供方呼叫遙測覆蓋缺口/i,
    })
  ).toHaveCount(2);
  await expect(page.locator('a[href="/admin/troubleshooting"]').first()).toBeVisible();

  await page.goto('/admin/coverage');
  await expect(page.getByRole('heading', { name: /^Customer service workspace$|^客户服务工作区$|^客戶服務工作區$/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Service status|Follow-up queue|服务状态|跟进队列|服務狀態|跟進隊列/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Packages|^Package overview|^套餐|^方案/i })).toHaveCount(0);
  await expect(page.getByText(/Customers needing service follow-up|需要服务跟进的客户|需要服務跟進的客戶/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open package actions|打开套餐操作|打開方案操作/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Inspect subscription|查看订阅|檢查訂閱/i }).first()).toBeVisible();
  await expect(page.locator('a[href="/admin/plans"]').first()).toBeVisible();

  await page.goto('/admin/subscriptions');
  await expect(page.getByRole('heading', { name: /^Service risk queue$|^服务风险队列$|^服務風險隊列$/i })).toBeVisible();
  await expect(page.locator('a[href="/admin/subscriptions/sub_mvp"]')).toBeVisible();
  await expect(page.getByText(/Billing stats to refresh|待刷新账单统计|待刷新帳單統計/i).first()).toBeVisible();
  await expect(page.getByText(/Billing statistics current|账单统计当前|帳單統計當前/i).first()).toBeVisible();

  await page.goto('/admin/subscriptions/sub_mvp');
  await expect(page.getByRole('heading', { name: /Service status detail: Pro|服务状态详情：Pro|服務狀態詳情：Pro/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}#coverage-actions"]`)).toBeVisible();
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}"]`).first()).toBeVisible();
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();
  await expect(page.getByText(/Base budget|基础预算/i).first()).toBeVisible();
  await expect(page.getByText(/Effective budget|有效预算/i).first()).toBeVisible();
  await expect(page.getByText(/Billing statistics|账单统计|帳單統計/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Rebuild current-period billing snapshots|重建当前周期账单快照/i })).toHaveCount(0);
  await expect(page.getByText(/checkout|buy points|storefront/i)).toHaveCount(0);

  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(page.getByRole('heading', { name: /Npcink AI Demo|MVP Account|acct_mvp_enterprise_primary/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.getByText(/Package and top-up|套餐和加量|方案和加量/i).first()).toBeVisible();
  await expect(page.getByText(/Agency quote and trial|Agency 报价与试用/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Create Agency quote|创建 Agency 报价/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Approve 14-day trial|批准 14 天试用/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /View sites|查看站点|查看站點/i })).toBeVisible();

  await page.goto('/admin/accounts', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Users and current packages|客户与当前套餐|用户与当前套餐|使用者與目前方案/i })).toBeVisible();

  await page.goto('/admin/sites/site_mvp');
  await expect(page.getByRole('heading', { name: /MVP Site|site_mvp/i }).first()).toBeVisible();

  await page.goto('/admin/troubleshooting');
  await expect(page.getByRole('heading', { name: /Advanced Troubleshooting|高级排障|進階排障/i })).toBeVisible();
  const runtimeEvidenceSection = page.locator('#runtime-evidence');
  await expect(runtimeEvidenceSection.getByRole('heading', { name: /Runtime Resource Evidence|运行时资源证据/i })).toBeVisible();
  await expect(runtimeEvidenceSection.getByText(/Runtime resolution|运行时解析/i).first()).toBeVisible();
  await expect(page.locator('a[href="/admin/plugin-observability"]').first()).toBeVisible();
  await expect(page.locator('a[href="/admin/hosted-models"]')).toHaveCount(0);

  await page.goto('/admin/plans', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { level: 1, name: /Package catalog|Package overview|套餐目录|套餐概览|方案目錄|方案概覽/i })).toBeVisible();
  await expect(page.getByText(/Package initialization|套餐初始化|方案初始化/i).first()).toBeVisible();
  await expect(page.getByText(/Historical Free|历史 Free/i)).toHaveCount(0);
  await expect(page.getByText(/Pro/i).first()).toBeVisible();
  await expect(page.getByText(/Plus/i).first()).toBeVisible();
  await expect(page.getByText(/Agency/i).first()).toBeVisible();
  await expect(page.getByText(/Site limit|站点上限/i).first()).toBeVisible();
  const freePackageCard = page.getByRole('group', { name: /Free package|Free 套餐/i });
  await expect(freePackageCard.getByLabel(/Site limit: 3|站点上限: 3/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /Back to coverage|返回服务状态/i })).toHaveCount(0);
  await expect(page.locator('a[href="/admin/plans/free"]')).toBeVisible();
  await expect(page.locator('a[href="/admin/plans/pro"]')).toBeVisible();
  await expect(page.getByText(/checkout|buy points|storefront/i)).toHaveCount(0);

  await page.goto('/admin/plans/free', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Free|套餐详情/i }).first()).toBeVisible();
  await expect(page.getByText(/Current package values|当前生效值/i).first()).toBeVisible();

  await page.goto('/admin/plans/pro', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Pro|套餐详情/i }).first()).toBeVisible();
  await expect(page.getByText(/Current package values|当前生效值/i).first()).toBeVisible();
  await expect(page.getByText(/Site limit|站点上限/i).first()).toBeVisible();
  const editPackageValuesButton = page.getByRole('button', { name: /Edit package values|编辑套餐值/i });
  await expect(editPackageValuesButton).toHaveCount(1);
  await expect(page.getByText(/Structured package fields|结构化套餐字段/i)).toHaveCount(0);
  await expect(page.getByText(/Open advanced diagnostics|查看高级诊断/i)).toHaveCount(0);
  await expect(page.getByText(/Advanced information|高级信息/i)).toBeVisible();
  await editPackageValuesButton.click();
  const packageEditor = page.getByRole('dialog', { name: /Edit current package values|编辑当前套餐值/i });
  await expect(packageEditor).toBeVisible();
  await expect(packageEditor.getByText(/Structured package fields|结构化套餐字段/i)).toBeVisible();
  await expect(packageEditor.getByText(/Advanced JSON overrides|高级 JSON 覆盖项/i)).toBeVisible();
  await packageEditor.getByRole('button', { name: /Cancel|取消/i }).click();
  await expect(page.getByRole('link', { name: /Open subscriptions|查看订阅|查看訂閱/i })).toHaveAttribute(
    'href',
    `/admin/subscriptions?plan_id=${LONG_PLAN_ID}`
  );
  await expect(page.getByRole('link', { name: /Inspect detail|查看详情|查看詳情/i })).toHaveCount(0);
});

test('admin queue pages keep one primary header action and shared identifier treatment', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin/subscriptions');
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}"]`).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: /MVP Account/i }).first()).toBeVisible();

  await page.goto('/admin/accounts');
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}"]`).first()).toBeVisible();

  await page.goto('/admin/accounts');
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}"]`).first()).toBeVisible();
  await expect(page.getByText(/Npcink AI Demo/i)).toBeVisible();
  await expect(page.getByText(/Pilot customer\. Confirm package before public release\./i)).toBeVisible();
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toBeVisible();
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Users and current packages|客户与当前套餐|用户与当前套餐|使用者與目前方案/i })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: /Package|套餐|方案/i })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: /Next step|下一步/i })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: /Sites|站点|站點/i })).toBeVisible();
  await expect(page.locator(`a[href="/admin/subscriptions/sub_mvp"]`)).toHaveCount(0);
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}#site-footprint"]`)).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Open customer service status|打开客户服务状态|打開客戶服務狀態/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Details|详情|詳情/i }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Suspend account|暂停账户|暫停帳戶/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Restore account|恢复账户|恢復帳戶/i })).toHaveCount(0);
  await page.getByLabel(/Package kind|套餐类型|方案類型/i).selectOption('formal_free');
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toBeVisible();
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toHaveCount(0);
  await page.getByLabel(/Package kind|套餐类型|方案類型/i).selectOption('');
  await page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i).selectOption('uncovered');
  await expect(page.getByText(/Uncovered Account|未覆盖客户|未覆蓋客戶/i)).toBeVisible();
  await expect(page.getByText(/Free Account|免费客户|免費客戶/i)).toHaveCount(0);
  await page.getByLabel(/Coverage state|覆盖状态|覆蓋狀態/i).selectOption('');
  await page.getByText(/Add user|Add customer|添加用户|添加客户|新增使用者/i).click();
  await page.getByLabel(/Account ID|账户 ID|账号 ID|帳戶 ID/i).fill('acct_new_customer_free');
  await page.getByLabel(/Name|名称|名稱/i).fill('New Customer');
  await page.getByLabel(/Operator name|运营显示名|營運顯示名/i).fill('New Customer Display');
  await page.getByLabel(/Operator note|运营备注|營運備註/i).fill('Internal launch note');
  await page.getByRole('button', { name: /Create user|创建用户|建立使用者/i }).click();
  await expect(page.getByText(/User created|用户已创建|使用者已建立/i)).toBeVisible();
  await expect(page.getByText(/New Customer Display/i)).toBeVisible();
  await expect(page.getByText(/Internal launch note/i)).toBeVisible();

  await page.goto('/admin/plans', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('a[href="/admin/plans/pro"]').first()).toBeVisible();
  await page.goto('/admin/plans/pro', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText(/Current package values|当前生效值/i).first()).toBeVisible();
  await expect(page.getByText(/Advanced information|高级信息/i)).toBeVisible();
  await page.getByText(/Advanced information|高级信息/i).click();
  await expect(page.getByRole('button', { name: /^Diagnostics$|^诊断$/i })).toBeVisible();
  await page.getByRole('button', { name: /Release history|发布历史/i }).click();
  await expect(page.getByText(/Pro v1|pro_v1/i).first()).toBeVisible();
  await page.getByRole('button', { name: /Edit package values|编辑套餐值/i }).click();
  const packageEditor = page.getByRole('dialog', { name: /Edit current package values|编辑当前套餐值/i });
  await expect(packageEditor.getByRole('button', { name: /Restore .* suggested values|恢复 .* 建议值/i })).toBeVisible();
  await expect(packageEditor.getByRole('button', { name: /Restore saved values|还原当前已保存值|還原目前已儲存值/i })).toBeVisible();
  await packageEditor.getByRole('button', { name: /Cancel|取消/i }).click();
  await expect(page.getByRole('link', { name: /Open subscriptions|查看订阅|查看訂閱/i })).toHaveAttribute(
    'href',
    `/admin/subscriptions?plan_id=${LONG_PLAN_ID}`
  );
  await expect(page.getByText(/已发布|published/i).first()).toBeVisible();

  await page.goto('/admin/ai-resources', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /^Suppliers$|^供应商$/i })).toBeVisible();
  await expect(page.getByRole('tab', { name: /Model suppliers|模型供应商|模型供應商/i })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tab', { name: /All suppliers|全部供应商|全部供應商/i })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: /Diagnostics|诊断|診斷/i })).toHaveCount(0);
  await expect(page.getByText(/run_records/i).first()).toHaveCount(0);
  await expect(page.getByRole('link', { name: /View diagnostics|查看诊断|查看診斷/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Add model supplier|添加模型供应商|新增模型供應商/i })).toBeVisible();
});

test('admin support and detail pages keep bounded operator hierarchy', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(page.getByText('acct_mvp_ent...rimary').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open customer subscription|打开客户订阅/i })).toHaveCount(0);
  await expect(page.getByText(/Package and top-up|套餐和加量|方案和加量/i)).toBeVisible();
  await page.getByText(/Edit customer info|编辑客户信息|編輯客戶資訊/i).click();
  const operatorProfileForm = page.locator('form').filter({ hasText: /Operator note|运营备注|營運備註/i }).first();
  await operatorProfileForm.getByLabel(/Operator note|运营备注|營運備註/i).fill('Updated detail note');
  await operatorProfileForm.getByRole('button', { name: /Save|保存|儲存/i }).click();
  await expect(page.getByText(/Operator note has been saved|运营备注已保存|營運備註已儲存/i)).toBeVisible();
  await page.goto('/admin/accounts');
  await expect(page.getByText(/Updated detail note/i)).toBeVisible();
  await page.goto(`/admin/accounts/${LONG_ACCOUNT_ID}`);
  await expect(page.locator('[data-ui="trial-readiness-summary"]')).toHaveCount(0);
  await expect(page.getByText(/^(Top-up packs|加量包)$/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Small top-up|小加量包/i })).toBeVisible();
  await page.getByRole('button', { name: /Small top-up|小加量包/i }).click();
  let confirmDialog = page.getByRole('dialog');
  await expect(confirmDialog.getByText(/Confirm top-up pack|确认应用加量包|確認套用加量包/i)).toBeVisible();
  await confirmDialog.getByRole('button', { name: /Cancel|取消/i }).click();
  await expect(page.getByText(/Small top-up has been applied|小加量包 已应用|小加量包 已套用/i)).toHaveCount(0);
  await page.getByRole('button', { name: /Small top-up|小加量包/i }).click();
  confirmDialog = page.getByRole('dialog');
  await confirmDialog.getByRole('button', { name: /Apply top-up|应用加量包|套用加量包/i }).click();
  await expect(page.getByText(/Small top-up has been applied|小加量包 已应用|小加量包 已套用/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /View sites|查看站点|查看站點/i })).toBeVisible();
  await expect(page.getByLabel(/Plan Version|套餐版本|方案版本/i)).toBeHidden();
  await expect(page.getByLabel(/Email|邮箱|電子郵件/i)).toBeHidden();
  const advancedCoverageControls = page.locator('[data-ui="advanced-coverage-controls"]');
  await expect(advancedCoverageControls).toHaveJSProperty('open', false);
  await expect(page.getByRole('tab', { name: /Package|套餐/i })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tab', { name: /Usage|用量/i })).toBeVisible();
  await expect(page.getByRole('tab', { name: /Sites|站点|站點/i })).toBeVisible();
  await expect(advancedCoverageControls.getByRole('link', { name: /Inspect detail|查看详情|檢查詳情/i })).toBeHidden();
  await expect(advancedCoverageControls.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i })).toBeHidden();
  const packageActionReveal = page.getByText(/Repair subscription record|维修订阅记录|維修訂閱記錄/i);
  await packageActionReveal.click();
  await expect(advancedCoverageControls).toHaveJSProperty('open', true);
  const coverageBoundary = page.locator('#coverage-actions');
  await expect(advancedCoverageControls.getByRole('link', { name: /Inspect detail|查看详情|檢查詳情/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Change package|调整套餐|調整方案/i })).toBeVisible();
  await expect(page.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i })).toBeVisible();
  await expect(page.getByRole('textbox', { name: /Coverage package version|覆盖套餐版本|覆蓋方案版本/i })).toHaveCount(0);
  await expect(page.getByText(/applied automatically|自动应用|自動套用/i).first()).toBeVisible();
  await page.getByRole('button', { name: /Suspend coverage|暂停覆盖|暫停覆蓋/i }).click();
  confirmDialog = page.getByRole('dialog');
  await expect(confirmDialog.getByText(/Confirm suspension|确认暂停覆盖|確認暫停覆蓋/i)).toBeVisible();
  await confirmDialog.getByRole('button', { name: /Suspend coverage|暂停覆盖|暫停覆蓋/i }).click();
  await expect(coverageBoundary.getByText(/已暂停|suspended/i).first()).toBeVisible();
  await packageActionReveal.click();
  await page.getByRole('button', { name: /Cancel coverage|取消覆盖|取消覆蓋/i }).click();
  confirmDialog = page.getByRole('dialog');
  await expect(confirmDialog.getByText(/Confirm cancellation|确认取消覆盖|確認取消覆蓋/i)).toBeVisible();
  await confirmDialog.getByRole('button', { name: /Cancel coverage|取消覆盖|取消覆蓋/i }).click();
  await expect(coverageBoundary.getByText(/已取消|canceled/i).first()).toBeVisible();
  await packageActionReveal.click();
  await page.getByRole('combobox', { name: /Coverage package option|覆盖套餐选项|覆蓋方案選項/i }).selectOption(LONG_PLAN_ID);
  await page.getByRole('button', { name: /Change package|调整套餐|調整方案/i }).click();
  confirmDialog = page.getByRole('dialog');
  await expect(confirmDialog.getByText(/Confirm subscription repair|确认维修订阅记录|確認維修訂閱記錄/i)).toBeVisible();
  await confirmDialog.getByRole('button', { name: /Change package|调整套餐|調整方案/i }).click();
  await expect(coverageBoundary.getByText(/Pro/i).first()).toBeVisible();
  await expect(page.getByText(/Covered by paid package|付费套餐已覆盖|付費方案已覆蓋/i).first()).toBeVisible();
  await page.getByRole('tab', { name: /Sites|站点|站點/i }).click();
  await expect(page.getByRole('tab', { name: /Sites|站点|站點/i })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('a[href="/admin/sites/site_mvp"]').first()).toBeVisible();

  await page.goto('/admin/sites/site_mvp');
  await expect(page.getByText('site_mvp').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Open service status|Open coverage|打开服务状态|打开覆盖|打開服務狀態|打開覆蓋/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Inspect subscription detail|查看订阅详情|檢查訂閱詳情/i }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /View audit trail|查看审计/i }).first()).toBeVisible();
  await page.getByText(/Inspect audit follow-up|查看审计跟进|查看稽核跟進/i).click();
  await expect(page.getByText(/Recent audit summary for this site|此站点的近期审计摘要/i)).toBeVisible();
  await expect(page.getByText(/subscription\.bind|provider_connection\.sync/i).first()).toBeVisible();

  await page.goto('/admin/subscriptions/sub_mvp');
  await expect(page.getByRole('heading', { name: /Service status detail: Pro|服务状态详情：Pro|服務狀態詳情：Pro/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /Customer|客户/i }).first()).toBeVisible();
  await expect(page.locator(`a[href="/admin/accounts/${LONG_ACCOUNT_ID}"]`).first()).toBeVisible();
  await expect(page.getByText(/Related sites|关联站点|關聯站點/i).first()).toBeVisible();
  await expect(page.getByText(/Billing statistics|账单统计|帳單統計/i).first()).toBeVisible();
  await expect(page.getByText(/Boundary|边界|邊界/i).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /View audit trail|查看审计/i }).first()).toBeVisible();
  await expect(page.getByText(/Recent audit summary for this subscription|此订阅的近期审计摘要/i)).toBeVisible();
});

test('admin navigation stays customer-first', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);

  await page.goto('/admin');

  const adminNav = page.getByRole('navigation', { name: /管理后台|admin/i });
  const adminPrimaryNav = page.locator('[data-ui="admin-primary-nav"]');
  const primaryLinks = adminPrimaryNav.locator('a.admin-nav-link');
  await expect(primaryLinks).toHaveCount(8);
  await expect(primaryLinks.nth(0)).toHaveAttribute('href', '/admin');
  await expect(primaryLinks.nth(1)).toHaveAttribute('href', '/admin/accounts');
  await expect(primaryLinks.nth(2)).toHaveAttribute('href', '/admin/support-requests');
  await expect(primaryLinks.nth(3)).toHaveAttribute('href', '/admin/coverage');
  await expect(primaryLinks.nth(4)).toHaveAttribute('href', '/admin/plans');
  await expect(primaryLinks.nth(5)).toHaveAttribute('href', '/admin/ai-resources');
  await expect(primaryLinks.nth(6)).toHaveAttribute('href', '/admin/troubleshooting');
  await expect(primaryLinks.nth(7)).toHaveAttribute('href', '/admin/service-settings');
  await expect(adminPrimaryNav.getByText(/^Workspace$|^工作台$/i)).toBeVisible();
  await expect(adminPrimaryNav.getByText(/^Customer Ops$|^客户运营$/i)).toBeVisible();
  await expect(adminPrimaryNav.getByText(/^Runtime Plane$|^运行面$/i)).toBeVisible();
  await expect(adminPrimaryNav.getByText(/^Diagnostics$|^诊断$/i)).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Overview$|^概览$|^概覽$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Customers$|^客户$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Sites$|^站点$|^站點$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Packages \/ Service Status$|^套餐\/服务状态$|^方案\/服務狀態$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Providers$|^供应商$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Model Binding$|^模型绑定$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Runtime Diagnostics$|^运行诊断$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Hosted Models$|^托管模型$|^託管模型$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Service Risks$|^服务风险$|^服務風險$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Portal Users$|^自助注册用户$|^自助註冊使用者$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Package Catalog$|^套餐目录$|^方案目錄$/i })).toBeVisible();
  await expect(adminNav.getByRole('link', { name: /^Credit Packs$|^积分包$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Members$|^成员$|^成員$/i })).toHaveCount(0);
  await expect(adminNav.getByRole('link', { name: /^Plugin Observability$|^插件观测$|^外掛觀測$/i })).toHaveCount(0);

  await page.goto('/admin/subscriptions');
  const main = page.locator('main');
  await expect(main.getByRole('link', { name: /^Customer register$|^客户目录$|^客戶目錄$/i })).toHaveCount(0);
  await expect(main.getByRole('link', { name: /^Registered users$|^注册用户$|^註冊使用者$/i })).toHaveCount(0);
  await expect(main.getByRole('link', { name: /^Service follow-up$|^服务跟进$|^服務跟進$/i })).toHaveCount(0);
  await expect(main.getByRole('link', { name: /^Subscription records$|^订阅记录$|^訂閱記錄$/i })).toHaveCount(0);
  await expect(main.getByRole('button', { name: /^All|^全部|^全部/i }).first()).toBeVisible();
});

test('admin operator path stays usable on mobile viewport', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installAdminMocks(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: /Platform state comes first|先看平台概况/i })).toBeVisible();

  await page.goto('/admin/sites/site_mvp');
  await expect(page.getByRole('heading', { name: /MVP Site|site_mvp/i }).first()).toBeVisible();
});
