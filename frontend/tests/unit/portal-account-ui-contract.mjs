import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const clientPath = resolve(process.cwd(), 'src/lib/portal-client.ts');
const navbarPath = resolve(process.cwd(), 'src/components/portal/PortalNavbar.tsx');
const accountPagePath = resolve(process.cwd(), 'src/app/portal/account/page.tsx');

const clientSource = readFileSync(clientPath, 'utf8');
const navbarSource = readFileSync(navbarPath, 'utf8');
const accountSource = readFileSync(accountPagePath, 'utf8');

assert.match(
  clientSource,
  /getIdentityProviders\(\)/,
  'portal client must expose identity provider status'
);

assert.match(
  clientSource,
  /'\/auth\/identity-providers'/,
  'portal client must call the identity provider status endpoint'
);

assert.match(
  clientSource,
  /intent: 'bind'/,
  'QQ bind start must use bind intent instead of login intent'
);

assert.match(
  clientSource,
  /'\/auth\/qq\/unbind'/,
  'portal client must expose QQ unbind'
);

assert.match(
  clientSource,
  /requestEmailChangeCode[\s\S]*'\/account\/email-change\/request'/,
  'portal client must expose the authenticated email-change request endpoint'
);

assert.match(
  clientSource,
  /verifyEmailChangeCode[\s\S]*'\/account\/email-change\/verify'/,
  'portal client must expose the authenticated email-change verification endpoint'
);

assert.match(
  navbarSource,
  /href: '\/portal\/account'/,
  'portal navigation must include the account center'
);

assert.match(
  accountSource,
  /resolvePortalContactEmail/,
  'account center must resolve a customer-readable contact instead of showing principal IDs as the account'
);

assert.match(
  accountSource,
  /session\.email/,
  'account center must prefer the explicit session email before falling back to legacy contact refs'
);

assert.match(
  accountSource,
  /data-portal-account="contact-info"/,
  'account center must make contact information the primary customer-facing account surface'
);

assert.match(
  accountSource,
  /portalClient\.requestEmailChangeCode[\s\S]*portalClient\.verifyEmailChangeCode/,
  'account center must support self-service verified email changes'
);
assert.match(
  accountSource,
  /<Modal[\s\S]*data-portal-account="email-change-dialog"/,
  'account center must keep verified email changes in a focused dialog'
);

assert.doesNotMatch(
  accountSource,
  /Ask the operator to update the contact email|请先让操作员更新联系人信息/,
  'account center must not tell users to ask an operator for normal email changes'
);

assert.doesNotMatch(
  accountSource,
  /data-portal-account="support-details"/,
  'customer account page must not render an internal support details disclosure'
);

assert.doesNotMatch(
  accountSource,
  /session\.(account_id|role|principal_id)|BackofficeIdentifier|maskSupportIdentifier/,
  'customer account page must not expose internal account, role, or principal identifiers'
);

assert.doesNotMatch(
  accountSource,
  /label:\s*t\('portal\.account\.email_label'[\s\S]*value:\s*accountEmail/,
  'top account summary must not show the raw principal-derived account value'
);

assert.match(
  accountSource,
  /portalClient\.startQqBind/,
  'account center must start QQ binding through the shared client'
);

assert.match(
  accountSource,
  /portalClient\.unbindQqLogin/,
  'account center must support QQ unbinding through the shared client'
);

console.log('portal_account_ui_contract: ok');
