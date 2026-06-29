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
  navbarSource,
  /href: '\/portal\/account'/,
  'portal navigation must include the account center'
);

assert.match(
  accountSource,
  /邮箱是主账号，QQ 用作快捷登录绑定/,
  'account center must keep email as the primary account and QQ as quick login'
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
