import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const bootstrapRoutePath = resolve(process.cwd(), 'src/app/admin/auth/bootstrap/route.ts');
const loginPagePath = resolve(process.cwd(), 'src/app/admin/login/page.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');

const bootstrapRouteSource = readFileSync(bootstrapRoutePath, 'utf8');
const loginPageSource = readFileSync(loginPagePath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');

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
  /t\('admin\.login_error_invalid'\)/,
  'admin login invalid-token copy must use the localized operator guidance'
);
assert.match(
  i18nSource,
  /'admin\.login_error_invalid': 'The admin bootstrap token is not valid\.[^']+'[\s\S]*'admin\.login_error_invalid': '后台启动令牌无效，[^']+'/,
  'admin login invalid-token guidance must exist in English and Simplified Chinese'
);
assert.match(
  loginPageSource,
  /createApiClient[\s\S]*resolveAdminLoginRedirect[\s\S]*\.request\('\/admin\/session'\)[\s\S]*router\.replace\(redirectTo\)/,
  'admin login must validate the server session before redirecting to a safe admin destination'
);
assert.match(
  loginPageSource,
  /if \(isCheckingSession\) \{[\s\S]*return <LoadingFallback \/>;/,
  'admin login must not show the token form before session validation finishes'
);

assert.match(
  loginPageSource,
  /t\('admin\.login_error_code'\)/,
  'admin login page must keep the localized machine error code visible for support'
);

assert.match(
  loginPageSource,
  /Trace:/,
  'admin login page must show a trace id when one is available'
);

console.log('admin_login_error_contract: ok');
