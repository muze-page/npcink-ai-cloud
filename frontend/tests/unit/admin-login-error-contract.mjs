import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const loginRoutePath = resolve(process.cwd(), 'src/app/admin/auth/login/route.ts');
const loginPagePath = resolve(process.cwd(), 'src/app/admin/login/page.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');

const loginRouteSource = readFileSync(loginRoutePath, 'utf8');
const loginPageSource = readFileSync(loginPagePath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');

assert.match(
  loginRouteSource,
  /function redirectToLogin\([\s\S]*errorCode:[\s\S]*url\.searchParams\.set\('error', errorCode\)/,
  'admin login proxy must redirect form-login failures back to the login page'
);

assert.match(
  loginRouteSource,
  /const wantsJson = contentType\.includes\('application\/json'\)/,
  'admin login proxy must preserve JSON behavior while improving browser form failures'
);

assert.match(
  loginRouteSource,
  /url\.searchParams\.set\('error',\s*errorCode\)/,
  'admin login proxy must preserve backend error codes for the login page'
);

assert.match(
  loginRouteSource,
  /url\.searchParams\.set\('redirect',\s*sanitizeAdminRedirect\(redirect\)\)/,
  'admin login proxy must preserve only safe admin redirects after login errors'
);

assert.match(
  loginPageSource,
  /auth\.admin_key_invalid/,
  'admin login page must special-case invalid admin key errors'
);

assert.match(
  loginPageSource,
  /t\('admin\.login_error_invalid'\)/,
  'admin login invalid-key copy must use the localized operator guidance'
);
assert.match(
  loginPageSource,
  /proxy\.admin_login_invalid_response[\s\S]*t\('admin\.login_error_upstream'\)/,
  'admin login must distinguish an invalid upstream response from an invalid key'
);
assert.match(
  i18nSource,
  /'admin\.login_error_invalid': 'The admin key is not valid\.[^']+'[\s\S]*'admin\.login_error_invalid': '管理员密钥无效，[^']+'/,
  'admin login invalid-key guidance must exist in English and Simplified Chinese'
);
assert.match(
  i18nSource,
  /'admin\.login_error_upstream': 'Cloud rejected[^']+'[\s\S]*'admin\.login_error_upstream': 'Cloud 内部登录转发配置异常，[^']+'/,
  'admin login upstream guidance must exist in English and Simplified Chinese'
);

assert.match(loginRouteSource, /buildBackendUrl\('\/admin\/auth\/login'\)/);
assert.match(loginRouteSource, /admin_key: adminKey/);
assert.doesNotMatch(loginRouteSource, /admin\/auth\/bootstrap|bootstrap token|admin_ref|principal_id/i);
assert.match(loginRouteSource, /resolveTrustedAdminOrigin/);
assert.match(loginRouteSource, /return new URL\(getPublicBaseUrl\(\)\)\.origin/);
assert.doesNotMatch(loginRouteSource, /request\.nextUrl\.origin/);
assert.doesNotMatch(loginRouteSource, /getExternalRequestOrigin/);
assert.match(
  loginRouteSource,
  /parsed\.pathname !== '\/admin' && !parsed\.pathname\.startsWith\('\/admin\/'\)/,
  'admin login redirects must reject lookalike paths such as /administrator'
);
assert.doesNotMatch(loginRouteSource, /!parsed\.pathname\.startsWith\('\/admin'\)/);
assert.doesNotMatch(loginPageSource, /admin\/auth\/bootstrap|bootstrap token|name="token"/i);
assert.match(
  loginPageSource,
  /createApiClient[\s\S]*resolveAdminLoginRedirect[\s\S]*\.request\('\/admin\/session'\)[\s\S]*router\.replace\(redirectTo\)/,
  'admin login must validate the server session before redirecting to a safe admin destination'
);
assert.match(
  loginPageSource,
  /if \(isCheckingSession\) \{[\s\S]*return <LoadingFallback \/>;/,
  'admin login must not show the key form before session validation finishes'
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
