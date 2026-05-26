import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const packageDisplayPath = resolve(root, 'src/lib/customer-package-display.ts');
const billingPagePath = resolve(root, 'src/app/portal/billing/page.tsx');
const siteRecordPath = resolve(root, 'src/app/portal/sites/[siteId]/page.tsx');

const packageDisplaySource = readFileSync(packageDisplayPath, 'utf8');
assert.match(
  packageDisplaySource,
  /planVersionId\?: string;/,
  'customer package display must accept planVersionId as a fallback input'
);
assert.match(
  packageDisplaySource,
  /inferPlanIdFromPlanVersionId/,
  'customer package display must expose a plan-version fallback resolver'
);

const billingPageSource = readFileSync(billingPagePath, 'utf8');
assert.match(
  billingPageSource,
  /function coerceFiniteNumber/,
  'Portal package page must guard invalid numeric snapshot totals'
);
assert.match(
  billingPageSource,
  /planVersionId: snapshotPlanVersionId/,
  'Portal package page must use planVersionId fallback when resolving the current package label'
);
assert.match(
  billingPageSource,
  /href=\{`\/portal\/sites\/\$\{selectedSiteId\}`\}/,
  'Portal package page must link users to the site record to inspect package and allowed actions'
);
assert.match(
  billingPageSource,
  /<details className="overflow-hidden rounded-\[1\.4rem\] border/,
  'Portal package page must keep package records behind an explicit details reveal'
);
assert.doesNotMatch(
  billingPageSource,
  /formatCurrency\(latestSnapshot\.totals\.cost\)/,
  'Portal package page must not format raw snapshot totals without validating the number'
);

const siteRecordSource = readFileSync(siteRecordPath, 'utf8');
assert.match(
  siteRecordSource,
  /This is the clearest place to confirm the current package, current period, your role, and allowed actions for this site\./,
  'Site record must explicitly position itself as the main read-only entry for package and access verification'
);
