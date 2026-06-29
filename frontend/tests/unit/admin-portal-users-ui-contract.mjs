import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/portal-users/page.tsx');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const proxyPath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');

const pageSource = readFileSync(pagePath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const proxySource = readFileSync(proxyPath, 'utf8');

assert.match(
  pageSource,
  /fetch\(`\/api\/admin\/portal-users\?\$\{buildQuery\(filters\)\}`/,
  'portal users page must load users through the admin proxy'
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
  /批量禁用需要填写原因/,
  'batch disable must require an operator reason'
);

assert.match(
  pageSource,
  /\/api\/admin\/portal-users\/\$\{encodeURIComponent\(user\.principal_id\)\}\/audit\?limit=50/,
  'portal users page must load principal-scoped audit details'
);

assert.match(
  pageSource,
  /用户审计详情/,
  'portal users page must expose a user audit detail inspector'
);

assert.match(
  pageSource,
  /最近禁用原因/,
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

assert.match(
  layoutSource,
  /href: '\/admin\/portal-users'/,
  'admin navigation must include the portal users surface'
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
