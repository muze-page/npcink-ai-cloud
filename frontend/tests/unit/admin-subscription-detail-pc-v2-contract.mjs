import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/subscriptions/[subscriptionId]/page.tsx'), 'utf8');
const commercialCopy = readFileSync(resolve(process.cwd(), 'src/lib/admin-commercial-copy.ts'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(page, /conclusionTitle[\s\S]*conclusionDescription[\s\S]*accountCoverageHref/, 'subscription detail must derive one current conclusion and one bounded next destination');
assert.match(page, /admin\.subscription_detail\.current_follow_up[\s\S]*hasSnapshotFollowUp[\s\S]*admin\.subscription_detail\.open_customer_coverage_action/, 'the first-screen action must follow snapshot and customer-coverage priority');
assert.doesNotMatch(page, /actions=\{\([\s\S]*admin\.back_to_subscriptions/, 'the header must not become a row of duplicate navigation actions');
assert.match(page, /BackofficeDisclosure[\s\S]*admin\.subscription_detail\.advanced_operational_evidence[\s\S]*admin\.subscription_detail\.commercial_status_title[\s\S]*admin\.subscription_detail\.covered_sites_label/, 'commercial, usage, site, and audit evidence must remain advanced detail');
assert.match(page, /BackofficeDiagnosticNotice[\s\S]*setLoadVersion/, 'initial read failures must preserve the route shell and provide bounded retry');
assert.doesNotMatch(page, /window\.location\.reload/, 'retry must not reload the entire admin application');

for (const text of [
  'Read current status and grace posture first.',
  'Use site detail and filtered audit evidence to confirm whether snapshot posture and impact are aligned.',
  'Open site detail for runtime and entitlement impact.',
]) {
  assert.ok(commercialCopy.includes(`'${text}'`), `known backend copy must be localized: ${text}`);
}

for (const key of [
  'admin.subscription_detail.load_error_title',
  'admin.subscription_detail.current_follow_up',
  'admin.subscription_detail.follow_up_focus',
  'admin.subscription_detail.conclusion_snapshot_title',
  'admin.subscription_detail.conclusion_coverage_title',
  'admin.subscription_detail.open_customer_coverage_action',
  'admin.subscription_detail.advanced_operational_evidence',
]) {
  const occurrences = Array.from(i18n.matchAll(new RegExp(`'${key.replaceAll('.', '\\.')}':`, 'g'))).length;
  assert.equal(occurrences, 2, `${key} must exist in English and Simplified Chinese`);
}

console.log('admin_subscription_detail_pc_v2_contract: ok');
