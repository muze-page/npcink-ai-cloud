import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const source = readFileSync(fromFrontendRoot('src/app/admin/portal-users/page.tsx'), 'utf8');

assert.match(source, /BackofficeLayer/, 'Portal user directory must use the compact operating header');
assert.match(source, /BackofficeSummaryStrip/, 'Portal user directory must expose a compact status summary');
assert.doesNotMatch(source, /BackofficePrimaryPanel|BackofficeMetricStrip|<table|overflow-x-auto/, 'Portal user directory must not restore the old hero metrics or wide table');

for (const parameter of ['q', 'status', 'package_alias', 'qq_bound', 'sort', 'offset', 'focus']) {
  assert.match(source, new RegExp(`searchParams\\.get\\('${parameter}'\\)`), `${parameter} must be URL-backed`);
}

assert.match(source, /loadedRequestKey[\s\S]*admin\.portal_users\.retained_notice/, 'failed filter loads must retain and honestly label the last successful page');
assert.match(source, /access-risk ordering applies to the current page/, 'client access-risk ordering must not be presented as global truth');
assert.match(source, /data-ui="portal-user-directory-item"/, 'users must render in a responsive task list');
assert.match(source, /id="portal-user-inspector"/, 'one user inspector must hold identity detail and follow-up actions');
assert.match(source, /admin\.portal_users\.open_customer_action/, 'the inspector must open the existing customer record');
assert.match(source, /admin\.portal_users\.audit_action/, 'audit must remain an explicit inspector action');

assert.match(source, /selectedPrincipalIds\.length > 0/, 'batch destructive actions must appear only after selection');
assert.match(source, /admin\.portal_users\.access_actions_title/, 'single-user disable must stay behind an explicit access-actions disclosure');
assert.match(source, /AdminLatestOperationButton/, 'auditable mutation receipts must use the compact latest-operation entry');
assert.match(source, /toast\.success/, 'transient mutation success must use global toast feedback');
assert.match(source, /does not create roles, permissions, payments, entitlements, or WordPress users/, 'the inspector must state the external-user boundary');

console.log('admin_portal_users_directory_v2_contract: ok');
