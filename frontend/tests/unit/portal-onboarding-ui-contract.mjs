import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const source = readFileSync(resolve(process.cwd(), 'src/app/portal/page.tsx'), 'utf8');
const connectSource = readFileSync(
  resolve(process.cwd(), 'src/components/portal/PortalSiteConnectPanel.tsx'),
  'utf8'
);
const sitesSource = readFileSync(
  resolve(process.cwd(), 'src/components/portal/PortalSitesWorkspace.tsx'),
  'utf8'
);

assert.match(source, /setupChecklistItems/);
assert.match(source, /portal\.home\.onboarding_title/);
assert.match(
  source,
  /onboarding_site_title[\s\S]*onboarding_package_title/,
  'first-use checklist must cover only site connection and package readiness'
);
assert.doesNotMatch(
  source,
  /onboarding_qq_|getIdentityProviders|currentSiteActiveKeyCount|getSiteDiagnostics/,
  'Portal home onboarding must not load identity, key, or diagnostic detail'
);
assert.match(
  source,
  /const selectedSite = session\.selected_context\?\.site \|\| null/,
  'onboarding readiness must use the explicit selected context site'
);
assert.doesNotMatch(
  source,
  /sites\s*\[\s*0\s*\]|const selectedSite\s*=\s*(?:getVisiblePortalSites|session\??\.sites)/,
  'onboarding may show the bounded site list but must not infer current context from it'
);
assert.match(
  source,
  /selectedSite\?\.status === 'active'[\s\S]*Boolean\(selectedSiteUrl\)/,
  'site readiness must use the session site status and URL'
);
assert.match(
  source,
  /\/portal\/sites\/\$\{encodeURIComponent\(selectedSite\.site_id\)\}#service-status/,
  'site follow-up must open the lazy-loaded site detail status section'
);
assert.match(
  source,
  /requiredAttentionItems = setupChecklistItems\.filter[\s\S]*shouldShowOnboardingChecklist = requiredAttentionItems\.length > 0/,
  'first-use checklist must hide after all required steps are complete'
);
assert.doesNotMatch(source, /localStorage|sessionStorage/);

const connectClientCalls = Array.from(
  connectSource.matchAll(/portalClient\s*\.\s*([A-Za-z0-9_]+)\s*\(/g),
  (match) => match[1]
);
assert.deepEqual(
  connectClientCalls,
  ['createAddonConnection'],
  'site connection panel must expose only the WordPress addon handoff'
);
assert.doesNotMatch(
  connectSource,
  /createSite|connect_site_heading|connect_site_desc|connect_site_action|type="url"/,
  'manual self-create UI and calls must stay deleted'
);
assert.match(
  connectSource,
  /if \(!hasAddonConnectionContext\)[\s\S]*return;[\s\S]*createAddonConnection/,
  'addon connection must fail closed before requesting Cloud when handoff context is incomplete'
);
assert.match(
  sitesSource,
  /addonConnectMode[\s\S]*portalClient\.listAddonConnectionAccounts\(\)[\s\S]*accounts=\{addonAccounts\}/,
  'WordPress addon handoff must load candidates from the dedicated addon account endpoint'
);
assert.match(
  connectSource,
  /useState\(''\)[\s\S]*accounts\.some\(\(account\) => account\.account_id === selectedAccountId\)[\s\S]*account_id: selectedAccountId/,
  'addon binding must require an explicit eligible account selection'
);
assert.doesNotMatch(
  `${sitesSource}\n${connectSource}`,
  /(?:addonAccounts|accounts|candidates)\s*(?:\?\.)?\s*\[\s*0\s*\]|(?:addonAccounts|accounts|candidates)\.at\(\s*0\s*\)/,
  'addon binding must never auto-select the first candidate'
);

console.log('portal_onboarding_ui_contract: ok');
