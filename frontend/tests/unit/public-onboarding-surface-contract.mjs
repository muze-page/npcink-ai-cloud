import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const home = read('src/app/page.tsx');
const login = read('src/app/portal/login/page.tsx');
const register = read('src/app/portal/register/page.tsx');
const health = read('src/app/api/health/route.ts');
const publicShell = read('src/components/public/PublicSiteShell.tsx');
const legacyFooter = read('src/components/ui/Footer.tsx');
const legacyNavbar = read('src/components/ui/Navbar.tsx');
const proxy = read('src/proxy.ts');

for (const [name, source] of [
  ['home', home],
  ['public shell', publicShell],
  ['legacy footer', legacyFooter],
  ['legacy navbar', legacyNavbar],
]) {
  assert.doesNotMatch(
    source,
    /href=["']\/admin\/login["']/,
    `${name} must not advertise the operator login on a public surface`
  );
}

assert.match(home, /<QqLoginButton/, 'home must expose the QQ login entry');
assert.match(login, /<QqLoginButton/, 'login must expose the QQ login entry');
assert.match(register, /<QqLoginButton/, 'registration must expose the QQ login entry');
assert.match(proxy, /X-Robots-Tag[\s\S]*noindex/, 'admin responses must opt out of indexing');

assert.match(health, /status: 'healthy'/, 'machine health must retain a stable status field');
assert.match(health, /checked_at:/, 'machine health must expose its check time');
assert.doesNotMatch(
  health,
  /process\.uptime|npm_package_version|NODE_ENV/,
  'public machine health must not expose runtime internals'
);

console.log('public_onboarding_surface_contract: ok');
