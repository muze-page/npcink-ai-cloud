import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const pageSource = readFileSync(resolve(root, 'src/app/admin/credit-packs/page.tsx'), 'utf8');
const proxySource = readFileSync(resolve(root, 'src/app/api/admin/[...path]/route.ts'), 'utf8');
const billingSource = readFileSync(resolve(root, 'src/app/portal/billing/page.tsx'), 'utf8');

assert.match(
  pageSource,
  /\/api\/admin\/credit-packs/,
  'Admin credit pack page must use the admin service-plane catalog endpoint'
);
assert.match(
  pageSource,
  /validity_days/,
  'Admin credit pack page must expose pack validity days'
);
assert.match(
  pageSource,
  /MANAGED_TIERS[\s\S]*free[\s\S]*plus[\s\S]*pro[\s\S]*agency/,
  'Admin credit pack recommendations must place Plus between Free and Pro'
);
assert.doesNotMatch(
  pageSource,
  /wallet|permanent|unlimited/i,
  'Admin credit pack page must not present packs as wallet or permanent credit'
);
assert.match(
  proxySource,
  /normalized === 'credit-packs'[\s\S]*\/internal\/service\/admin\/credit-packs/,
  'Admin proxy must route credit pack writes to the admin-prefixed service endpoint'
);
assert.match(
  billingSource,
  /portal\.usage\.credit_packs_desc[\s\S]*portal\.usage\.credit_packs_period_badge/,
  'Portal billing must show the purchased credit validity window at section level'
);
assert.match(
  billingSource,
  /portal\.package\.plus_title/,
  'Portal billing must expose the Plus package tier'
);
