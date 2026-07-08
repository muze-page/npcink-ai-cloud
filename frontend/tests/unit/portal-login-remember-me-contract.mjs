import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const loginSource = readFileSync(resolve(root, 'src/app/portal/login/page.tsx'), 'utf8');
const hookSource = readFileSync(resolve(root, 'src/hooks/useSession.ts'), 'utf8');
const clientSource = readFileSync(resolve(root, 'src/lib/portal-client.ts'), 'utf8');

assert.match(
  clientSource,
  /interface PortalLoginCodeVerifyRequest[\s\S]*remember_me\?: boolean/,
  'Portal login verify request must accept optional remember_me'
);

assert.match(
  hookSource,
  /verifyLoginCode: \(email: string, code: string, options\?: \{ rememberMe\?: boolean \}\)/,
  'useSession must expose rememberMe as an optional login verification option'
);

assert.match(
  hookSource,
  /portalClient\.verifyLoginCode\(\{ email, code, remember_me: Boolean\(options\.rememberMe\) \}\)/,
  'useSession must pass rememberMe through as remember_me'
);

assert.match(
  loginSource,
  /rememberMe: false/,
  'Portal login form must default remember me to off'
);

assert.match(
  loginSource,
  /auth\.remember_me_7_days/,
  'Portal login page must offer the 7-day remember-me option'
);

assert.match(
  loginSource,
  /const handleResendCode = async \(\) =>[\s\S]*requestLoginCode\(normalizedEmail\)[\s\S]*auth\.code_resent/,
  'Portal login verification step must allow resending the email verification code'
);

assert.match(
  loginSource,
  /auth\.resend_code/,
  'Portal login verification step must show a resend-code action'
);

assert.match(
  loginSource,
  /verifyLoginCode\(normalizedEmail, normalizedCode, \{ rememberMe: form\.rememberMe \}\)/,
  'Portal login page must send rememberMe during verification'
);

assert.match(
  loginSource,
  /await verifyLoginCode\(normalizedEmail, normalizedCode, \{ rememberMe: form\.rememberMe \}\)[\s\S]*window\.location\.replace\('\/portal'\)/,
  'Portal login page must use a full-page navigation after successful cookie-backed verification'
);

console.log('portal_login_remember_me_contract: ok');
