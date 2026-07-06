import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const bootstrapRoutePath = resolve(process.cwd(), 'src/app/admin/auth/bootstrap/route.ts');
const loginPagePath = resolve(process.cwd(), 'src/app/admin/login/page.tsx');

const bootstrapRouteSource = readFileSync(bootstrapRoutePath, 'utf8');
const loginPageSource = readFileSync(loginPagePath, 'utf8');

assert.match(
  bootstrapRouteSource,
  /redirectToLogin\(request,\s*errorCode/,
  'admin bootstrap proxy must redirect form-login failures back to the login page'
);

assert.match(
  bootstrapRouteSource,
  /wantsLoginRedirect:\s*!contentType\.includes\('application\/json'\)/,
  'admin bootstrap proxy must preserve JSON behavior while improving browser form failures'
);

assert.match(
  bootstrapRouteSource,
  /url\.searchParams\.set\('error',\s*errorCode\)/,
  'admin bootstrap proxy must preserve backend error codes for the login page'
);

assert.match(
  bootstrapRouteSource,
  /url\.searchParams\.set\('redirect',\s*sanitizeAdminRedirect\(redirect\)\)/,
  'admin bootstrap proxy must preserve only safe admin redirects after login errors'
);

assert.match(
  loginPageSource,
  /auth\.admin_bootstrap_token_invalid/,
  'admin login page must special-case invalid bootstrap token errors'
);

assert.match(
  loginPageSource,
  /NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN/,
  'admin login invalid-token copy must point operators at the current token name'
);

assert.match(
  loginPageSource,
  /Error code:/,
  'admin login page must keep the machine error code visible for support'
);

assert.match(
  loginPageSource,
  /Trace:/,
  'admin login page must show a trace id when one is available'
);

console.log('admin_login_error_contract: ok');
