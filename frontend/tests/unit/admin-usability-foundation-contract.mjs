import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const read = (path) => readFileSync(fromFrontendRoot(path), 'utf8');

const layoutSource = read('src/app/admin/layout.tsx');
const subscriptionSource = read('src/app/admin/subscriptions/[subscriptionId]/page.tsx');
const siteSource = read('src/app/admin/sites/[siteId]/page.tsx');
const supportSource = read('src/app/admin/support-requests/page.tsx');
const overviewSource = read('src/app/admin/page.tsx');
const advisorSource = read('src/app/admin/ai-advisor/page.tsx');
const auditSummarySource = read('src/components/admin/AdminAuditSummaryPanel.tsx');
const horizontalScrollSource = read('src/components/admin/AdminHorizontalScroll.tsx');
const latestOperationSource = read('src/components/admin/AdminLatestOperationDialog.tsx');

assert.match(
  layoutSource,
  /activePrefixes: \['\/admin\/coverage', '\/admin\/subscriptions'\]/,
  'subscription routes must remain under the service-status navigation context'
);

assert.match(subscriptionSource, /return <AdminRouteSkeleton \/>/, 'subscription detail must use the shared route skeleton');
assert.equal(
  subscriptionSource.match(/onClick=\{\(\) => void handleBillingSnapshotRefresh\(\)\}/g)?.length || 0,
  1,
  'subscription detail must expose one billing-statistics refresh action'
);
assert.match(subscriptionSource, /AdminLatestOperationButton/, 'subscription receipts must use the compact latest-operation entry');
assert.match(subscriptionSource, /toast\.success\(/, 'subscription mutation success must use Toast feedback');
assert.match(subscriptionSource, /snapshotRefreshError[\s\S]*BackofficeDiagnosticNotice/, 'subscription mutation failures must stay in the affected section through the shared alert surface');

assert.match(siteSource, /return <AdminRouteSkeleton \/>/, 'site detail must not render a blank loading body');
assert.match(siteSource, /usage_without_limit/, 'site detail must explain usage when no limit is configured');
assert.doesNotMatch(siteSource, /setSiteNotice/, 'site activation success must not expand the page with an inline notice');

assert.match(supportSource, /const appliedStatus = queueParams\.get\('status'\) \|\| ''/, 'ticket queue must open on all statuses and persist status in the URL');
assert.match(supportSource, /window\.history\.replaceState/, 'ticket queue URL updates must not race through asynchronous router transitions');
assert.match(supportSource, /support_requests_topic_filter_label/, 'ticket topic filter must have an accessible name');
assert.match(supportSource, /support_requests_search_label/, 'ticket search must have an accessible name');

assert.match(overviewSource, /home_extended_evidence_title/, 'overview secondary evidence must be disclosed explicitly');
assert.ok(
  advisorSource.indexOf('<AdvisorEvaluationDetails>') < advisorSource.indexOf('<SignalPanel branch={data.ai} />'),
  'advisor signal detail must stay inside the advanced evaluation disclosure'
);

assert.match(auditSummarySource, /role="alert"[\s\S]*setReloadKey/, 'audit summary failures must provide a local retry');
assert.match(horizontalScrollSource, /role="region"[\s\S]*tabIndex=\{0\}/, 'wide admin data regions must be keyboard focusable');
assert.match(latestOperationSource, /<Modal[\s\S]*<AdminMutationReceipt/, 'latest operation must open durable receipt detail in a modal');

console.log('admin_usability_foundation_contract: ok');
