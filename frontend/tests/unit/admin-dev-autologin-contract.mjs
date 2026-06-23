import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const adminRoutePath = resolve(process.cwd(), 'src/app/admin/dev-entry/route.ts');
const portalRoutePath = resolve(process.cwd(), 'src/app/portal/dev-entry/route.ts');
const miniDevDockPath = resolve(process.cwd(), 'src/components/dev/MiniDevDock.tsx');

const adminRouteSource = readFileSync(adminRoutePath, 'utf8');
const portalRouteSource = readFileSync(portalRoutePath, 'utf8');
const miniDevDockSource = readFileSync(miniDevDockPath, 'utf8');

assert.match(
  adminRouteSource,
  /buildBackendUrl\('\/admin\/auth\/bootstrap'\)/,
  'admin dev-entry must bootstrap through /admin/auth/bootstrap'
);
assert.match(
  adminRouteSource,
  /token:\s*getAdminBootstrapToken\(\)/,
  'admin dev-entry must send the admin bootstrap token'
);
assert.match(
  adminRouteSource,
  /admin_ref:\s*getAdminBootstrapAdminRef\(\)/,
  'admin dev-entry must send the bootstrap admin ref'
);
assert.match(
  adminRouteSource,
  /redirect:\s*resolveRedirectPath\(request\)/,
  'admin dev-entry must redirect into the requested admin path after bootstrap'
);
assert.match(
  adminRouteSource,
  /buildDeniedRedirect\(request,\s*'auth\.dev_entry_disabled'\)/,
  'admin dev-entry must deny when mini-dev entry is disabled'
);
assert.match(
  adminRouteSource,
  /if \(isMiniDevRequestHost\(candidate\)\) \{\s*return true;\s*\}/m,
  'admin dev-entry must allow mini-host requests directly instead of relying only on CLOUD_PUBLIC_BASE_URL'
);
assert.match(
  adminRouteSource,
  /if \(!requestedRedirect\.startsWith\('\/admin'\)\) \{\s*return '\/admin';\s*\}/m,
  'admin dev-entry must only honor redirects that stay inside /admin'
);
assert.match(
  adminRouteSource,
  /buildDeniedRedirect\(request,\s*'auth\.dev_entry_unreachable'\)/,
  'admin dev-entry must surface backend-unreachable failures'
);
assert.match(
  adminRouteSource,
  /appendForwardHeaders\(response,\s*nextResponse\)/,
  'admin dev-entry must forward backend auth headers to the browser'
);
assert.match(
  adminRouteSource,
  /Origin:\s*resolvedOrigin/,
  'admin dev-entry must forward the resolved external origin'
);
assert.match(
  adminRouteSource,
  /Referer:\s*`\$\{resolvedOrigin\}\/`/,
  'admin dev-entry must forward a referer rooted at the resolved external origin'
);
assert.match(
  adminRouteSource,
  /response\.headers\.set\('Cache-Control',\s*'no-store'\)/,
  'admin dev-entry deny path must disable caching'
);
assert.match(
  adminRouteSource,
  /nextResponse\.headers\.set\('Cache-Control',\s*'no-store'\)/,
  'admin dev-entry success path must disable caching'
);

assert.match(
  portalRouteSource,
  /buildBackendUrl\('\/portal\/v1\/auth\/code\/request'\)/,
  'portal dev-entry must request a login code from /portal/v1/auth/code/request'
);
assert.match(
  portalRouteSource,
  /buildBackendUrl\('\/portal\/v1\/auth\/code\/verify'\)/,
  'portal dev-entry must verify the login code through /portal/v1/auth/code/verify'
);
assert.match(
  portalRouteSource,
  /body:\s*JSON\.stringify\(\{\s*email\s*\}\)/,
  'portal dev-entry code request must send the dev portal email'
);
assert.match(
  portalRouteSource,
  /body:\s*JSON\.stringify\(\{\s*email,\s*code\s*\}\)/,
  'portal dev-entry verify request must send the email and returned code'
);
assert.match(
  portalRouteSource,
  /'X-Npcink-Debug-Portal-Link':\s*'1'/,
  'portal dev-entry must opt into the debug portal-link flow'
);
assert.match(
  portalRouteSource,
  /if \(!codeResponse\.ok \|\| !code\)/,
  'portal dev-entry must fail closed when the login code response is unusable'
);
assert.match(
  portalRouteSource,
  /if \(!verifyResponse\.ok\)/,
  'portal dev-entry must fail closed when code verification fails'
);
assert.match(
  portalRouteSource,
  /if \(!requestedRedirect\.startsWith\('\/portal'\)\) \{\s*return '\/portal';\s*\}/m,
  'portal dev-entry must only honor redirects that stay inside /portal'
);
assert.match(
  portalRouteSource,
  /if \(isMiniDevRequestHost\(candidate\)\) \{\s*return true;\s*\}/m,
  'portal dev-entry must allow mini-host requests directly instead of relying only on CLOUD_PUBLIC_BASE_URL'
);
assert.match(
  portalRouteSource,
  /appendForwardHeaders\(verifyResponse,\s*nextResponse\)/,
  'portal dev-entry must forward backend auth headers to the browser'
);
assert.match(
  portalRouteSource,
  /nextResponse\.headers\.set\('Cache-Control',\s*'no-store'\)/,
  'portal dev-entry success path must disable caching'
);

assert.doesNotMatch(
  miniDevDockSource,
  /dev\.current_site_shortcut/,
  'Mini dev dock must not expose the redundant current-site shortcut'
);
assert.match(
  miniDevDockSource,
  /\/portal\/dev-entry\?origin=\$\{encodeURIComponent\(currentOrigin\)\}&redirect=\$\{encodeURIComponent\('\/portal'\)\}/,
  'Mini dev dock must send the portal shortcut to the portal workspace entry'
);
assert.match(
  miniDevDockSource,
  /\/admin\/dev-entry\?origin=\$\{encodeURIComponent\(currentOrigin\)\}&redirect=\$\{encodeURIComponent\('\/admin'\)\}/,
  'Mini dev dock must send the admin shortcut to the admin workspace entry'
);
