import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const sitesPagePath = resolve(process.cwd(), 'src/app/portal/sites/page.tsx');
const siteRecordPagePath = resolve(process.cwd(), 'src/app/portal/sites/[siteId]/page.tsx');
const portalClientPath = resolve(process.cwd(), 'src/lib/portal-client.ts');

const sitesPageSource = readFileSync(sitesPagePath, 'utf8');
const siteRecordPageSource = readFileSync(siteRecordPagePath, 'utf8');
const portalClientSource = readFileSync(portalClientPath, 'utf8');

assert.match(
  portalClientSource,
  /async removeSite\(siteId: string\)[\s\S]*\/sites\/\$\{siteId\}\/remove/,
  'portal client must expose the service-side soft-remove endpoint'
);

assert.match(
  sitesPageSource,
  /remove_sites[\s\S]*portalClient\.removeSite/,
  '/portal/sites must show a permission-gated remove action wired to the backend remove endpoint'
);

assert.match(
  sitesPageSource,
  /portal\.remove_site_confirm/,
  '/portal/sites must explain that removal stops service, revokes active keys, and keeps history before confirming'
);

assert.match(
  sitesPageSource,
  /portal\.site_remove_success/,
  '/portal/sites must show the service stopped, keys revoked, history kept success state'
);

assert.match(
  siteRecordPageSource,
  /remove_sites[\s\S]*portalClient\.removeSite/,
  '/portal/sites/[siteId] must keep the same permission-gated remove action available from the site record'
);

assert.doesNotMatch(
  `${sitesPageSource}\n${siteRecordPageSource}\n${portalClientSource}`,
  /request\(['"]DELETE['"],\s*`?\/sites/,
  'portal site removal must remain a backend-governed soft remove, not a frontend hard delete'
);

console.log('portal_sites_remove_contract: ok');
