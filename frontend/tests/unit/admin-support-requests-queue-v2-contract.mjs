import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const source = readFileSync(fromFrontendRoot('src/app/admin/support-requests/page.tsx'), 'utf8');

assert.match(source, /BackofficeLayer/, 'ticket queue must use the compact operating header');
assert.match(source, /BackofficeSummaryStrip/, 'ticket queue must expose a compact operating summary');
assert.doesNotMatch(source, /BackofficePrimaryPanel|BackofficeStackCard|<table/, 'ticket queue must not restore the old card stack or a wide table');

for (const parameter of ['status', 'topic', 'q', 'sort', 'offset', 'focus']) {
  assert.match(source, new RegExp(`queueParams\\.get\\('${parameter}'\\)`), `${parameter} must be URL-backed`);
}
assert.match(source, /window\.history\.replaceState/, 'queue filter updates must synchronously preserve the current PC URL state');

assert.match(source, /activeRequestKeyRef[\s\S]*requestSequenceRef[\s\S]*hasLoadedRef/, 'ticket reads must dedupe initial requests and reject stale responses');
assert.match(source, /loadedRequestKey[\s\S]*support_requests_retained_notice/, 'failed filter loads must retain and honestly label the last successful page');
assert.match(source, /risk ordering applies to the current page/, 'client risk ordering must not be presented as global SLA truth');

assert.match(source, /data-ui="support-request-queue-item"/, 'tickets must render as a responsive task list');
assert.match(source, /id="support-request-inspector"/, 'ticket queue must provide one persistent inspector');
assert.ok(source.indexOf('support_requests_customer_submission_title') < source.indexOf('support_requests_internal_handling_title'), 'customer submission must be separated from internal handling');
assert.equal(source.match(/<textarea/g)?.length || 0, 1, 'internal handling must expose one note editor in the inspector, not one editor per row');

assert.match(source, /method: 'PATCH'/, 'the bounded ticket status update must remain available');
assert.match(source, /setActionError[\s\S]*role="alert"/, 'ticket update failures must stay in the inspector context');
assert.match(source, /toast\.success/, 'successful ticket updates must use global toast feedback');
assert.match(source, /admin\.support_requests_open_conversation_action/, 'the inspector must explicitly open the full conversation surface');
assert.match(source, /no WordPress write is created/, 'the queue must state its Cloud service-plane boundary');

console.log('admin_support_requests_queue_v2_contract: ok');
