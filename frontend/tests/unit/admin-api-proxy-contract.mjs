import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const source = readFileSync(routePath, 'utf8');

assert.match(
  source,
  /return normalized \? `\/internal\/service\/admin\/\$\{normalized\}` : '\/internal\/service\/admin';/,
  'admin GET proxy must read from /internal/service/admin'
);

assert.doesNotMatch(
  source,
  /if \(method !== 'GET'\)\s*{\s*const sessionResult = await requireAdminSessionData\(request\);/s,
  'admin proxy must not skip session validation for GET requests'
);

assert.match(
  source,
  /const sessionResult = await requireAdminSessionData\(request\);\s*if \(sessionResult instanceof NextResponse\)/,
  'admin proxy must validate the backend admin session before forwarding any method'
);

assert.match(
  source,
  /\^accounts\\\/\[\^\/\]\+\\\/subscription\(\?:\\\/\(\?:suspend\|cancel\)\)\?\$/,
  'admin account subscription writes must route to the backend admin service namespace'
);

assert.match(
  source,
  /return `\/internal\/service\/admin\/\$\{normalized\}`;/,
  'admin-prefixed write exceptions must preserve /internal/service/admin'
);

assert.doesNotMatch(
  source,
  /audio-providers/,
  'admin proxy must not expose the retired env-backed audio provider settings routes'
);

assert.doesNotMatch(
  source,
  /web-search-providers|image-source-providers/,
  'admin proxy must not expose retired env-backed capability provider settings routes'
);

assert.match(
  source,
  /normalized === 'audio-jobs'[\s\S]*?return '\/internal\/service\/admin\/audio-jobs';/,
  'audio workbench job creation must route through the backend admin service namespace'
);

assert.match(
  source,
  /normalized === 'ai-resources\/profile-preferences'[\s\S]*?return '\/internal\/service\/admin\/ai-resources\/profile-preferences';/,
  'AI resource profile preference saves must route through the backend admin service namespace'
);

assert.match(
  source,
  /normalized === 'provider-connections\/preview-catalog'[\s\S]*?return '\/internal\/service\/admin\/provider-connections\/preview-catalog';/,
  'provider connection catalog previews must route through the backend admin service namespace'
);

assert.match(
  source,
  /\^subscriptions\\\/\[\^\/\]\+\\\/topup\$/,
  'subscription top-up writes must route to the service top-up endpoint'
);

assert.match(
  source,
  /return normalized \? `\/internal\/service\/\$\{normalized\}` : '\/internal\/service';/,
  'default admin write proxy must forward to /internal/service instead of a missing /admin root'
);

assert.doesNotMatch(
  source,
  /return normalized \? `\/admin\/\$\{normalized\}` : '\/admin';/,
  'admin write proxy must not forward to the missing backend /admin root'
);

console.log('admin_api_proxy_contract: ok');
