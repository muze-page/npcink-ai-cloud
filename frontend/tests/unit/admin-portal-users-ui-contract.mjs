import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const pagePath = fromFrontendRoot('src/app/admin/portal-users/page.tsx');
const layoutPath = fromFrontendRoot('src/app/admin/layout.tsx');
const accountsPath = fromFrontendRoot('src/app/admin/accounts/page.tsx');
const proxyPath = fromFrontendRoot('src/app/api/admin/[...path]/route.ts');

const pageSource = readFileSync(pagePath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const accountsSource = readFileSync(accountsPath, 'utf8');
const proxySource = readFileSync(proxyPath, 'utf8');

assert.match(
  pageSource,
  /fetch\(`\/api\/admin\/portal-users\?\$\{buildQuery\(filters, offset\)\}`/,
  'portal users page must load users through the admin proxy'
);

assert.match(
  pageSource,
  /<ListPagination[\s\S]*offset=\{offset\}[\s\S]*total=\{total\}/,
  'portal users page must expose all filtered users through pagination'
);

assert.match(
  pageSource,
  /source', 'portal_self_registration'/,
  'portal users page must default to the self-registration source'
);

assert.match(
  pageSource,
  /\/api\/admin\/portal-users\/\$\{encodeURIComponent\(user\.principal_id\)\}\/disable/,
  'portal users page must expose a principal-scoped disable action'
);

assert.match(
  pageSource,
  /\/api\/admin\/portal-users\/batch-disable/,
  'portal users page must expose the lightweight batch disable endpoint'
);

assert.match(
  pageSource,
  /if \(!reason\)[\s\S]*admin\.portal_users\.batch_reason_required/,
  'batch disable must require an operator reason'
);

assert.match(
  pageSource,
  /\/api\/admin\/portal-users\/\$\{encodeURIComponent\(user\.principal_id\)\}\/audit\?limit=50/,
  'portal users page must load principal-scoped audit details'
);

assert.match(
  pageSource,
  /admin\.portal_users\.audit_modal_title/,
  'portal users page must expose a user audit detail inspector'
);

assert.match(
  pageSource,
  /admin\.portal_users\.latest_disable_reason/,
  'portal users audit inspector must expose disable reason evidence'
);

assert.match(
  pageSource,
  /session_version/,
  'portal users page must surface session version invalidation data'
);

assert.match(
  pageSource,
  /QQ/,
  'portal users page must display QQ binding state'
);

assert.doesNotMatch(
  pageSource,
  /CustomerAdminTabs/,
  'portal users page must use the shared admin sidebar instead of duplicate customer tabs'
);

assert.doesNotMatch(
  layoutSource,
  /admin\.nav_group_customer_service[\s\S]*href: '\/admin\/portal-users'/,
  'portal users must not return as a top-level customer-ops sidebar entry'
);

assert.match(
  accountsSource,
  /href="\/admin\/portal-users"[\s\S]*admin\.accounts\.open_portal_users_action/,
  'accounts page must expose portal users as a secondary entry'
);

assert.match(
  proxySource,
  /\^portal-users\\\/\[\^\/\]\+\\\/disable\$/,
  'admin proxy must route portal user disable writes to the admin backend namespace'
);

assert.match(
  proxySource,
  /normalized === 'portal-users\/batch-disable'/,
  'admin proxy must route portal user batch disable writes to the admin backend namespace'
);

assert.doesNotMatch(
  pageSource,
  /\/admin\/accounts\?/,
  'portal user management must stay separate from account billing management'
);

assert.doesNotMatch(
  pageSource,
  /restore|恢复/,
  'portal users page must not introduce restore controls'
);

console.log('admin_portal_users_ui_contract: ok');
