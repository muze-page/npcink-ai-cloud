import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/ai-advisor/page.tsx'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(page, /advisorHeadlineText\(branch\.headline, t\)/, 'default diagnosis headline must localize known backend conclusions');
assert.match(page, /advisorSummaryText\(advisor\.summary \|\| branch\.operator_summary, t\)/, 'default diagnosis summary must localize known backend conclusions');
assert.match(page, /advisorEvidenceLabel\(item\.kind, item\.label, t\)/, 'default evidence labels must use operator-facing copy');
assert.match(page, /BackofficeDiagnosticNotice/, 'initial Advisor failure must preserve a scoped retry shell');
assert.doesNotMatch(page, /flex min-h-\[60vh\] items-center justify-center/, 'Advisor must not replace the route with a generic centered error');

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
