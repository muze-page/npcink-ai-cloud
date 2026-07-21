import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const legacySiteSelectionPath = resolve(root, 'src/hooks/usePortalSiteSelection.ts');
const sessionSource = readFileSync(resolve(root, 'src/hooks/useSession.ts'), 'utf8');
const sitesSource = readFileSync(resolve(root, 'src/components/portal/PortalSitesWorkspace.tsx'), 'utf8');

assert.equal(
  existsSync(legacySiteSelectionPath),
  false,
  'the compatibility site-selection hook must stay deleted'
);

assert.match(
  sessionSource,
  /const selectSite = useCallback[\s\S]*portalClient\.selectSite\(siteId\)[\s\S]*session: response\.data/,
  'site selection must replace the client session with the strict session returned by Cloud'
);

assert.match(
  sitesSource,
  /const handleSelectSite = async \(siteId: string\)[\s\S]*await selectSite\(siteId\)/,
  'site selection must be initiated only by an explicit workspace action'
);

assert.doesNotMatch(
  sitesSource,
  /router\.refresh\(\)|usePortalSiteSelection|sites\s*\[\s*0\s*\]/,
  'site selection must not restore route-refresh compatibility or first-site fallback behavior'
);

console.log('portal_cookie_route_refresh_contract: ok');
