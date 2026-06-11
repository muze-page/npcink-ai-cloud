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
