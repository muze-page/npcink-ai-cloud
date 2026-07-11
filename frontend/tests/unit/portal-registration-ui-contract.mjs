import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const clientPath = resolve(process.cwd(), 'src/lib/portal-client.ts');
const proxyPath = resolve(process.cwd(), 'src/proxy.ts');
const loginPagePath = resolve(process.cwd(), 'src/app/portal/login/page.tsx');
const registerPagePath = resolve(process.cwd(), 'src/app/portal/register/page.tsx');

const clientSource = readFileSync(clientPath, 'utf8');
const proxySource = readFileSync(proxyPath, 'utf8');
const loginSource = readFileSync(loginPagePath, 'utf8');
const registerSource = readFileSync(registerPagePath, 'utf8');

assert.match(
  clientSource,
  /PortalRegistrationCodeRequest/,
  'portal client must expose a registration code request contract'
);
assert.match(
  clientSource,
  /site_url\?: string;/,
  'portal registration request must not require a site URL for account creation'
);

assert.match(
  clientSource,
  /'\/register\/code\/request'/,
  'portal client must call the registration code request endpoint'
);

assert.match(
  clientSource,
  /'\/register\/verify'/,
  'portal client must call the registration verify endpoint'
);

assert.match(
  proxySource,
  /pathname === '\/portal\/login'[\s\S]*pathname === '\/portal\/register'[\s\S]*pathname === '\/portal\/dev-entry'/,
  'portal registration must remain a public entry page, not redirect to login'
);

assert.match(
  loginSource,
  /href="\/portal\/register"/,
  'portal login page must link new users to the registration page'
);
assert.match(
  loginSource,
  /portal\.login\.existing_label[\s\S]*<form[\s\S]*href="\/portal\/register"/,
  'portal login page must put the email login form and Free account entry in the same primary card'
);
assert.doesNotMatch(
  loginSource,
  /BackofficePrimaryPanel|BackofficeLayer/,
  'portal login page must not push the real login form below large explanatory panels'
);

assert.match(
  registerSource,
  /portalClient\.requestRegistrationCode/,
  'portal registration page must request registration codes through the shared client'
);

assert.match(
  registerSource,
  /const handleResendCode = async \(\) =>[\s\S]*portalClient\.requestRegistrationCode[\s\S]*portal\.register\.code_resent/,
  'portal registration verification step must allow resending the email verification code'
);

assert.match(
  registerSource,
  /auth\.resend_code/,
  'portal registration verification step must show a resend-code action'
);

assert.match(
  registerSource,
  /portalClient\.verifyRegistration/,
  'portal registration page must verify registration codes through the shared client'
);
assert.match(
  registerSource,
  /useSession/,
  'portal registration page must use the shared session controller after verification'
);
assert.match(
  registerSource,
  /const \{ isAuthenticated, isLoading, refresh \} = useSession\(\);[\s\S]*!isLoading && isAuthenticated[\s\S]*router\.replace\('\/portal'\)/,
  'authenticated users must leave the Portal registration page for the default workspace'
);
assert.match(
  registerSource,
  /if \(isLoading \|\| isAuthenticated\) \{[\s\S]*return <LoadingFallback \/>;/,
  'the registration form must remain hidden while the existing session is resolving or redirecting'
);
assert.match(
  registerSource,
  /await portalClient\.verifyRegistration\([\s\S]*await refresh\(\)[\s\S]*window\.location\.replace\('\/portal'\)/,
  'portal registration must refresh the cookie-backed Portal session and use a full-page navigation before entering the dashboard'
);
assert.match(
  registerSource,
  /portal\.register\.chip[\s\S]*<form[\s\S]*portal\.register\.already_title/,
  'portal registration page must put the Free signup form and sign-in return path in the same primary card'
);
assert.doesNotMatch(
  registerSource,
  /BackofficePrimaryPanel|BackofficeLayer|portal\.register\.use_case|portal\.register\.site_url|portal\.register\.site_name|siteUrl|siteName/,
  'portal registration page must only ask for email by default and leave site binding to the WordPress plugin'
);

assert.match(
  registerSource,
  /QQ quick login can be bound after you sign in/,
  'portal registration copy must keep QQ as post-registration binding'
);

console.log('portal_registration_ui_contract: ok');
