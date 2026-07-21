import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const clientSource = read('src/lib/portal-client.ts');
const sessionHookSource = read('src/hooks/useSession.ts');
const homeSource = read('src/app/portal/page.tsx');
const billingSource = read('src/app/portal/billing/page.tsx');
const usageSource = read('src/app/portal/usage/page.tsx');
const auditSource = read('src/app/portal/audit/PortalAuditClient.tsx');
const supportListSource = read('src/app/portal/support/page.tsx');
const supportDetailSource = read('src/app/portal/support/[requestId]/page.tsx');
const commercialCatalogSource = read('src/hooks/usePortalCommercialCatalog.ts');
const paymentOrdersSource = read('src/hooks/usePortalPaymentOrders.ts');
const sitesSource = read('src/components/portal/PortalSitesWorkspace.tsx');
const connectSource = read('src/components/portal/PortalSiteConnectPanel.tsx');

const sessionStart = clientSource.indexOf('export interface PortalSession {');
const sessionEnd = clientSource.indexOf('\nexport interface PortalSelectedContext', sessionStart);
assert.ok(sessionStart >= 0 && sessionEnd > sessionStart, 'PortalSession contract block must exist');
const portalSessionBlock = clientSource.slice(sessionStart, sessionEnd);

function interfaceBlock(name) {
  const marker = new RegExp(`export interface ${name}(?: extends [^{]+)? \\{`);
  const match = marker.exec(clientSource);
  const start = match?.index ?? -1;
  assert.ok(start >= 0, `${name} contract block must exist`);
  const blockStart = start + (match?.[0].length || 0);
  const nextInterface = clientSource.indexOf('\nexport interface ', blockStart);
  const nextType = clientSource.indexOf('\nexport type ', blockStart);
  const candidates = [nextInterface, nextType].filter((index) => index > start);
  const end = candidates.length ? Math.min(...candidates) : clientSource.length;
  return clientSource.slice(start, end);
}

function assertNoInternalPortalFields(name, fields) {
  const block = interfaceBlock(name);
  for (const field of fields) {
    assert.doesNotMatch(
      block,
      new RegExp(`^\\s*${field}\\??:`, 'm'),
      `${name} must not expose internal Portal field ${field}`
    );
  }
}

for (const requiredField of ['email', 'sites', 'selected_context', 'auth_mode', 'session']) {
  assert.match(
    portalSessionBlock,
    new RegExp(`^\\s*${requiredField}:`, 'm'),
    `PortalSession must retain bounded top-level field ${requiredField}`
  );
}

for (const forbiddenField of [
  'principal_id',
  'account_id',
  'accounts',
  'site_id',
  'role',
  'allowed_actions',
  'current_subscription',
  'entitlements',
  'site_name',
  'created_at',
  'metadata',
]) {
  assert.doesNotMatch(
    portalSessionBlock,
    new RegExp(`^\\s*${forbiddenField}\\??:`, 'm'),
    `PortalSession must not restore top-level compatibility field ${forbiddenField}`
  );
}

assert.match(
  clientSource,
  /export interface PortalSelectedContext \{[\s\S]*site: Site;[\s\S]*allowed_actions: string\[\];[\s\S]*current_subscription: PortalCurrentSubscription \| null;/,
  'site permissions and subscription must remain nested under selected_context'
);
assert.match(
  sessionHookSource,
  /return session\?\.selected_context\?\.site \|\| null/,
  'the selected-site hook must read only selected_context.site'
);

const internalProjectionFields = [
  'account_id',
  'principal_id',
  'site_admin_ref',
  'identity_type',
  'role',
  'allowed_actions',
  'admin_note',
  'email',
  'metadata',
];

for (const name of [
  'PortalAccountEntitlements',
  'PortalSiteEntitlements',
  'PortalIdentityProviderBinding',
  'PortalIdentityProvidersResponse',
  'PortalSiteSummaryRecord',
  'PortalUsageSummaryPayload',
  'PortalMonitoringOverviewSummary',
  'PortalDiagnosticAdvisorSummary',
  'PortalPluginObservabilitySummary',
  'PortalMediaObservabilitySummary',
  'PortalVectorObservabilitySummary',
  'PortalAIInsightResponse',
  'PortalAIInsightHistoryResponse',
  'PortalAuditSummary',
  'PortalAuditEventList',
  'PortalBillingReconciliation',
  'PortalSupportRequest',
  'PortalSupportRequestMessage',
  'PortalSupportRequestAttachment',
  'PortalSupportRequestListPayload',
]) {
  assertNoInternalPortalFields(name, internalProjectionFields);
}

assert.doesNotMatch(
  clientSource,
  /export type ProductIdentityType\b/,
  'the unused ProductIdentityType compatibility alias must stay removed'
);
assert.match(
  clientSource,
  /export interface PortalSiteEntitlements extends PortalAccountEntitlements \{[\s\S]*site: PortalSiteDetail;[\s\S]*subscription: PortalCurrentSubscription \| null;[\s\S]*plan_version: PortalSitePlanVersion \| null;[\s\S]*entitlement_snapshot: PortalSiteEntitlementSnapshot \| null;/,
  'site entitlements must model the current public site, subscription, plan, and snapshot projection'
);
assert.match(
  clientSource,
  /export type Entitlements = PortalAccountEntitlements;/,
  'the compatibility type name must point only at the bounded account quota projection'
);
for (const forbiddenField of [
  'site_name',
  'current_period_start',
  'current_period_end',
  'requests_limit',
  'tokens_limit',
  'features',
]) {
  assert.doesNotMatch(
    interfaceBlock('PortalSiteEntitlements'),
    new RegExp(`^\\s*${forbiddenField}\\??:`, 'm'),
    `PortalSiteEntitlements must not restore compatibility field ${forbiddenField}`
  );
}
assert.doesNotMatch(
  interfaceBlock('PortalAccountEntitlements'),
  /^\s*(?:site_id|site|subscription|plan_version|entitlement_snapshot|policy)\??:/m,
  'account entitlements must not pretend to return site commercial detail fields'
);

assert.doesNotMatch(
  clientSource,
  /unbindQqLogin\(\)[\s\S]{0,180}principal_id/,
  'QQ unbind response must not restore principal_id'
);
assert.doesNotMatch(
  clientSource,
  /listBillingSnapshots\(siteId: string\)[\s\S]{0,260}(?:account_id|site_admin_ref|\brole)\??:/,
  'site billing response must not restore internal account or role fields'
);

function collectSources(path) {
  const stats = statSync(path);
  if (stats.isDirectory()) {
    return readdirSync(path).flatMap((entry) => collectSources(join(path, entry)));
  }
  return ['.ts', '.tsx'].includes(extname(path)) ? [readFileSync(path, 'utf8')] : [];
}

const portalSessionConsumers = [
  ...collectSources(resolve(root, 'src/app/portal')),
  ...collectSources(resolve(root, 'src/components/portal')),
  ...collectSources(resolve(root, 'src/hooks')),
].join('\n');

assert.doesNotMatch(
  portalSessionConsumers,
  /\bsession\s*\??\.\s*(?:principal_id|account_id|accounts|site_id|role|allowed_actions|current_subscription|entitlements|site_name|created_at|metadata)\b/,
  'Portal production code must not consume removed Session compatibility fields'
);
assert.doesNotMatch(
  portalSessionConsumers,
  /\b(?:sites|accounts|candidates|addonAccounts|visibleSites)\s*(?:\?\.)?\s*\[\s*0\s*\]|\b(?:sites|accounts|candidates|addonAccounts|visibleSites)\.at\(\s*0\s*\)/,
  'Portal production code must not infer context from a candidate first item'
);

for (const [name, source] of [
  ['usage', usageSource],
  ['audit', auditSource],
  ['support list', supportListSource],
  ['support detail', supportDetailSource],
]) {
  assert.match(source, /contextSiteId/, `${name} must derive an explicit context site id`);
  assert.match(
    source,
    /if \(!isAuthenticated \|\| !(?:contextSiteId|requestContextSiteId)/,
    `${name} must fail closed before account requests when context is absent`
  );
  assert.match(source, /useLayoutEffect/, `${name} must clear stale state before context paint`);
  assert.match(source, /PortalEmptyState/, `${name} must render a stable missing-context state`);
}

assert.match(
  homeSource,
  /const contextSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''[\s\S]*useLayoutEffect\([\s\S]*accountEntitlementsRequestVersionRef[\s\S]*setAccountEntitlements\(null\)[\s\S]*if \(!isAuthenticated \|\| !contextSiteId\) return/,
  'Portal home account projection must synchronously clear, invalidate stale responses, and fail closed without selected context'
);
assert.match(
  billingSource,
  /const contextSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''[\s\S]*contextSiteId,[\s\S]*siteSelectionRequired = !contextSiteId/,
  'billing must pass selected context to its account hooks and expose a missing-context state'
);
for (const [name, source] of [
  ['commercial catalog', commercialCatalogSource],
  ['payment orders', paymentOrdersSource],
]) {
  assert.match(
    source,
    /if \(!isAuthenticated \|\| !requestContextSiteId\)/,
    `${name} requests must fail closed without selected context`
  );
  assert.match(
    source,
    /useLayoutEffect\([\s\S]*(?:requestVersionRef|loadRequestVersionRef)\.current \+= 1/,
    `${name} must invalidate in-flight responses when context changes`
  );
}

assert.doesNotMatch(
  usageSource,
  /creditLedgerSiteId|portal-usage-site|siteId:\s*[^\n,}]+/,
  'account usage must not restore a per-site filter or site query parameter'
);

assert.match(
  sitesSource,
  /portalClient\.listAddonConnectionAccounts\(\)[\s\S]*accounts=\{addonAccounts\}/,
  'addon binding candidates must come from the dedicated projection'
);
assert.match(
  connectSource,
  /const \[selectedAccountId, setSelectedAccountId\] = useState\(''\)[\s\S]*accounts\.some\(\(account\) => account\.account_id === selectedAccountId\)/,
  'addon binding must require explicit selection of an eligible candidate'
);
assert.equal(
  existsSync(resolve(root, 'src/hooks/usePortalSiteSelection.ts')),
  false,
  'the legacy site-selection compatibility hook must stay deleted'
);

console.log('portal_session_context_contract: ok');
