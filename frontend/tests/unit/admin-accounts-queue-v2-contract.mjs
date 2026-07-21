import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const source = readFileSync(resolve(root, 'src/app/admin/accounts/page.tsx'), 'utf8');
const routeSource = readFileSync(resolve(root, '../app/api/routes/service.py'), 'utf8');
const serviceSource = readFileSync(resolve(root, '../app/domain/commercial/mixins/_admin_mixin.py'), 'utf8');

assert.match(source, /BackofficeLayer[\s\S]*BackofficeSummaryStrip/, 'customer directory must use a compact operating header and summary strip');
assert.doesNotMatch(source, /BackofficePrimaryPanel|AdminHorizontalScroll|<table/, 'customer directory must not regress to a hero-card or horizontal-table layout');

assert.match(source, /usePathname[\s\S]*useRouter[\s\S]*useSearchParams/, 'customer queue state must be addressable from the route');
for (const parameter of ['q', 'status', 'expires_before', 'coverage_state', 'package_kind', 'top_plan_id', 'internal', 'sort', 'offset', 'focus']) {
  assert.match(source, new RegExp(`searchParams\\.get\\('${parameter}'\\)|${parameter}:`), `${parameter} must participate in route-backed customer queue state`);
}

assert.match(source, /activeRequestKeyRef[\s\S]*requestSequenceRef/, 'customer reads must deduplicate Strict Mode requests and reject stale responses');
assert.match(source, /loadedRequestKey[\s\S]*isShowingRetainedResults[\s\S]*last successfully loaded page/, 'failed filter loads must identify retained results honestly');
assert.doesNotMatch(source, /window\.location\.reload/, 'customer refresh recovery must preserve the current working state');

assert.match(routeSource, /sort: str = Query\(default="created_at", pattern="\^\(created_at\|display_name\|risk\)\$"\)/, 'internal customer API must accept global risk ordering');
assert.match(serviceSource, /account_risk_sort_key[\s\S]*coverage_follow_up_required[\s\S]*timedelta\(days=14\)[\s\S]*normalized_sort == "risk"/, 'risk sorting must happen in the service before pagination');
assert.match(source, /params\.set\('sort', sort\)[\s\S]*params\.set\('limit'[\s\S]*params\.set\('offset'/, 'customer queue must request server ordering before paginating');

assert.match(source, /role="list"[\s\S]*data-ui="account-queue-item"/, 'customers must render as a responsive task list');
assert.match(source, /aria-controls="account-inspector"[\s\S]*id="account-inspector"/, 'row inspection must have an accessible inspector target');
assert.match(source, /focus: account\.account_id/, 'customer inspector focus must persist in the URL');
assert.match(source, /href="\/admin\/portal-users"[\s\S]*admin\.accounts\.open_portal_users_action/, 'Portal users must remain a bounded secondary entry');

assert.match(source, /handleCreateAccount[\s\S]*bind_default_free[\s\S]*showSuccessToast/, 'customer creation and formal Free binding must remain explicit with non-shifting success feedback');
assert.match(source, /actionError[\s\S]*role="alert"/, 'customer creation failures must stay contextual');
assert.match(source, /does not create payment, entitlement, or WordPress write controls/, 'inspector copy must preserve the Cloud service-plane boundary');

console.log('admin_accounts_queue_v2_contract: ok');
