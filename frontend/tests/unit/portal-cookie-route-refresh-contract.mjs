import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const siteSelectionSource = readFileSync(resolve(root, 'src/hooks/usePortalSiteSelection.ts'), 'utf8');

assert.match(
  siteSelectionSource,
  /await selectSite\(normalizedSiteId\)[\s\S]*router\.replace\(nextUrl, \{ scroll: false \}\)[\s\S]*router\.refresh\(\)/,
  'Portal site selection must refresh the route tree after updating the cookie-backed selected site'
);

console.log('portal_cookie_route_refresh_contract: ok');
