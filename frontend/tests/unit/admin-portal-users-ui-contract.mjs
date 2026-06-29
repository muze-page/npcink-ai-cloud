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

assert.doesNotMatch(
  pageSource,
  /\/admin\/accounts\?/,
  'portal user management must stay separate from account billing management'
);

console.log('admin_portal_users_ui_contract: ok');
