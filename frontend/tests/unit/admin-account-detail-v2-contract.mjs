import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const source = readFileSync(fromFrontendRoot('src/app/admin/accounts/[accountId]/page.tsx'), 'utf8');
const architectureSource = readFileSync(
  fromFrontendRoot('../docs/cloud-admin-information-architecture-v2.md'),
  'utf8'
);

assert.match(
  source,
  /type AccountDetailTab = 'overview' \| 'commercial' \| 'credits' \| 'sites' \| 'audit'/,
  'customer detail must use the five task-oriented v2 sections'
);
assert.match(
  source,
  /useState<AccountDetailTab>\('overview'\)/,
  'customer detail must open on the read-only overview section'
);

for (const tab of ['overview', 'commercial', 'credits', 'sites', 'audit']) {
  assert.match(source, new RegExp(`id: '${tab}'`), `customer detail must keep the ${tab} section`);
}

assert.match(
  source,
  /activeDetailTab === 'commercial'[\s\S]*change_customer_package_label[\s\S]*agency_commerce_label/,
  'package changes and Agency decisions must stay in the commercial section'
);
assert.match(
  source,
  /activeDetailTab === 'credits'[\s\S]*topup_packs_label[\s\S]*credit_adjustment_label/,
  'top-up packs and credit adjustments must stay in the credits section'
);
assert.match(
  source,
  /if \(activeDetailTab === 'commercial'\)[\s\S]*loadPackagePlans\(\)[\s\S]*if \(activeDetailTab === 'credits'\)[\s\S]*loadQuotaSummary\(\)[\s\S]*loadCreditLedger\(\)[\s\S]*activeDetailTab === 'audit'[\s\S]*loadSiteRuntimeData\(siteIds\)/,
  'low-frequency commercial, credit, ledger, and site-runtime data must load from its owning tab'
);
for (const requestGuard of [
  'accountRequestedRef',
  'packagePlansRequestedRef',
  'quotaSummaryRequestedRef',
  'creditLedgerRequestedRef',
  'siteRuntimeRequestKeyRef',
]) {
  assert.match(
    source,
    new RegExp(`const ${requestGuard} = useRef`),
    `${requestGuard} must prevent duplicate tab or Strict Mode requests`
  );
}

assert.match(
  source,
  /admin\.account_detail\.more_account_actions[\s\S]*admin\.accounts\.suspend_account_action/,
  'account suspension must stay behind an explicit more-actions disclosure'
);
assert.match(source, /useToast\(\)/, 'customer and commercial success feedback must use global Toast');
assert.doesNotMatch(
  source,
  /data-ui="account-package-action-notice"/,
  'commercial success must not insert a permanent notice card into the working surface'
);

const auditSectionIndex = source.indexOf("activeDetailTab === 'audit'");
const firstReceiptIndex = source.indexOf('<AdminMutationReceipt receipt={accountStatusReceipt}');
const secondReceiptIndex = source.indexOf('<AdminMutationReceipt receipt={packageActionReceipt}');
assert.ok(auditSectionIndex >= 0, 'customer detail must include the audit section');
assert.ok(firstReceiptIndex > auditSectionIndex, 'account status receipt must render inside audit');
assert.ok(secondReceiptIndex > auditSectionIndex, 'commercial receipt must render inside audit');
assert.equal(
  source.match(/<AdminMutationReceipt receipt=/g)?.length || 0,
  2,
  'customer detail must not duplicate receipts across the default and audit surfaces'
);
assert.match(
  source,
  /<AdminAuditSummaryPanel[\s\S]*accountId=\{account\.account_id\}/,
  'customer audit section must expose the bounded account audit summary'
);
assert.match(
  source,
  /activeDetailTab === 'audit'[\s\S]*hasAdvancedChecks[\s\S]*id="advanced-checks"/,
  'low-frequency runtime checks must stay inside the audit/evidence section'
);
assert.match(
  source,
  /<ConfirmModal[\s\S]*pendingConfirmation/,
  'governed and destructive customer actions must keep object-specific confirmation'
);
assert.match(
  architectureSource,
  /`\/admin\/accounts\/\[accountId\]`[\s\S]*`detail`[\s\S]*overview, commercial, credits, sites, audit tabs/,
  'the implemented customer detail pilot must remain tied to the IA v2 route decision'
);

console.log('admin_account_detail_v2_contract: ok');
