import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const portalHomePath = resolve(process.cwd(), 'src/app/portal/page.tsx');
const source = readFileSync(portalHomePath, 'utf8');

assert.match(
  source,
  /setupChecklistItems/,
  'portal home must define a first-use checklist'
);

assert.match(
  source,
  /portal\.home\.onboarding_title/,
  'portal home must expose a first-use checklist title'
);

assert.match(
  source,
  /onboarding_site_title[\s\S]*onboarding_key_title[\s\S]*onboarding_package_title[\s\S]*onboarding_qq_title/,
  'first-use checklist must cover site, API key, package, and QQ binding'
);

assert.match(
  source,
  /portalClient\s*\.\s*getIdentityProviders/,
  'first-use checklist must reuse identity provider status for QQ binding'
);

assert.match(
  source,
  /currentSiteActiveKeyCount !== null && currentSiteActiveKeyCount > 0/,
  'first-use checklist must consider active API key state'
);

assert.match(
  source,
  /completedSetupCount < setupChecklistItems\.length/,
  'first-use checklist must hide after all setup steps are complete'
);

assert.doesNotMatch(
  source,
  /localStorage|sessionStorage/,
  'first-use checklist must be derived from account state rather than browser-only storage'
);

console.log('portal_onboarding_ui_contract: ok');
