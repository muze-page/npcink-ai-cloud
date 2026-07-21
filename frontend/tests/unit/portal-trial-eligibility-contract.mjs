import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const billingSource = readFileSync(resolve('src/app/portal/billing/page.tsx'), 'utf8');
const clientSource = readFileSync(resolve('src/lib/portal-client.ts'), 'utf8');
const i18nSource = readFileSync(resolve('src/lib/i18n.ts'), 'utf8');

assert.match(billingSource, /activeCommercialDialog === 'trial'/);
assert.match(billingSource, /portal\.package\.trial_dialog_title/);
assert.match(billingSource, /trial\?\.allowed_tiers/);
assert.match(billingSource, /trialState === 'eligible'/);
assert.match(billingSource, /trialState === 'active'/);
assert.match(billingSource, /trialState === 'used'/);
assert.match(billingSource, /trialState === 'blocked'/);
assert.match(
  billingSource,
  /trial\?\.available === true[\s\S]*'eligible'[\s\S]*'unavailable'/,
  'missing trial evidence must not be presented as an eligible trial'
);
assert.doesNotMatch(billingSource, /canTrialTier/);
assert.equal(
  (billingSource.match(/handleStartPlanTrial\(/g) || []).length,
  1,
  'trial mutation should be invoked only from the trial dialog'
);

assert.match(clientSource, /state\?: 'eligible' \| 'active' \| 'used' \| 'blocked' \| 'unavailable'/);
assert.match(clientSource, /allowed_tiers\?: Array<'plus' \| 'pro'>/);
assert.match(i18nSource, /'portal\.package\.paid_offer_desc': '\{\{amount\}\}\/30 天。'/);
assert.match(i18nSource, /'portal\.package\.trial_shared_desc'/);
assert.match(i18nSource, /'portal\.package\.trial_blocked_desc'/);

console.log('portal_trial_eligibility_contract: ok');
