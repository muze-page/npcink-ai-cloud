import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/ai-advisor/page.tsx'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const advisorRouteSources = [
  'ops-summary-history',
  'ops-summary-value',
  'ops-summary-preview',
  'ops-summary-review',
].map((routeName) => ({
  routeName,
  source: readFileSync(
    resolve(process.cwd(), `src/app/api/admin/advisor/${routeName}/route.ts`),
    'utf8'
  ),
}));

assert.match(page, /advisorHeadlineText\(branch\.headline, t\)/, 'default diagnosis headline must localize known backend conclusions');
assert.match(page, /advisorSummaryText\(advisor\.summary \|\| branch\.operator_summary, t\)/, 'default diagnosis summary must localize known backend conclusions');
assert.match(page, /advisorEvidenceLabel\(item\.kind, item\.label, t\)/, 'default evidence labels must use operator-facing copy');
assert.match(page, /BackofficeDiagnosticNotice/, 'initial Advisor failure must preserve a scoped retry shell');
assert.doesNotMatch(page, /flex min-h-\[60vh\] items-center justify-center/, 'Advisor must not replace the route with a generic centered error');

for (const { routeName, source } of advisorRouteSources) {
  const capabilityCheck = source.indexOf("requireAdminCapability(\n    sessionResult.session,\n    'can_review_diagnostics'");
  const internalToken = source.indexOf('getInternalAuthToken()');
  assert.ok(
    capabilityCheck >= 0 && internalToken > capabilityCheck,
    `${routeName} must require diagnostic capability before injecting the internal token`
  );
  assert.doesNotMatch(
    source,
    /error instanceof Error \? error\.message/,
    `${routeName} must not expose internal network exception details`
  );
  assert.match(
    source,
    /catch \{[\s\S]*?buildErrorResponse\([\s\S]*?'failed to reach advisor/,
    `${routeName} must return its stable public unreachable fallback`
  );
}

const reviewRouteSource = advisorRouteSources.find(
  ({ routeName }) => routeName === 'ops-summary-review'
)?.source || '';
assert.match(
  reviewRouteSource,
  /actor_ref: sessionResult\.session\.principal_id/,
  'Advisor review evidence must use canonical principal_id as actor_ref'
);
assert.doesNotMatch(
  reviewRouteSource,
  /platform_admin_ref/,
  'Advisor review route must not retain the retired admin identity alias'
);

const primaryStart = page.indexOf('<BackofficePrimaryPanel');
const advancedStart = page.indexOf("t('admin.ai_advisor.advanced_params'", primaryStart);
const primaryEnd = page.indexOf('</BackofficePrimaryPanel>', advancedStart);
assert.ok(primaryStart > 0 && advancedStart > primaryStart && primaryEnd > advancedStart, 'Advisor primary and advanced regions must remain explicit');
const primaryBeforeAdvanced = page.slice(primaryStart, advancedStart);
const advancedRegion = page.slice(advancedStart, primaryEnd);
assert.doesNotMatch(primaryBeforeAdvanced, /items=\{metricItems\}/, 'AI tokens, cache, and request cost must not dominate the default header');
assert.match(advancedRegion, /items=\{metricItems\}/, 'AI tokens, cache, and request cost must remain available in advanced evaluation parameters');

for (const key of [
  'admin.ai_advisor.diagnosis_provider_reliability',
  'admin.ai_advisor.diagnosis_provider_reliability_desc',
  'admin.ai_advisor.evidence_admin_overview',
  'admin.ai_advisor.evidence_runtime_diagnostics',
  'admin.ai_advisor.evidence_site_knowledge',
  'admin.ai_advisor.evidence_provider_calls',
]) {
  const occurrences = Array.from(i18n.matchAll(new RegExp(`'${key.replaceAll('.', '\\.')}':`, 'g'))).length;
  assert.equal(occurrences, 2, `${key} must exist in both English and Simplified Chinese dictionaries`);
}
