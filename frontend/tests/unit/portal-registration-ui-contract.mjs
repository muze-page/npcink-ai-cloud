import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const clientPath = resolve(process.cwd(), 'src/lib/portal-client.ts');
const loginPagePath = resolve(process.cwd(), 'src/app/portal/login/page.tsx');
const registerPagePath = resolve(process.cwd(), 'src/app/portal/register/page.tsx');

const clientSource = readFileSync(clientPath, 'utf8');
const loginSource = readFileSync(loginPagePath, 'utf8');
const registerSource = readFileSync(registerPagePath, 'utf8');

assert.match(
  clientSource,
  /PortalRegistrationCodeRequest/,
  'portal client must expose a registration code request contract'
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
  loginSource,
  /href="\/portal\/register"/,
  'portal login page must link new users to the registration page'
);

assert.match(
  registerSource,
  /portalClient\.requestRegistrationCode/,
  'portal registration page must request registration codes through the shared client'
);

assert.match(
  registerSource,
  /portalClient\.verifyRegistration/,
  'portal registration page must verify registration codes through the shared client'
);

assert.match(
  registerSource,
  /QQ quick login can be bound after you sign in/,
  'portal registration copy must keep QQ as post-registration binding'
);

console.log('portal_registration_ui_contract: ok');
