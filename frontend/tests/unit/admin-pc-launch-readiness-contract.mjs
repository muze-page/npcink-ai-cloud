import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const accountsSource = readFileSync(resolve(root, 'src/app/admin/accounts/page.tsx'), 'utf8');
const subscriptionsSource = readFileSync(resolve(root, 'src/app/admin/subscriptions/page.tsx'), 'utf8');
const plansSource = readFileSync(resolve(root, 'src/app/admin/plans/page.tsx'), 'utf8');
const creditPacksSource = readFileSync(resolve(root, 'src/app/admin/credit-packs/page.tsx'), 'utf8');
const serviceSettingsSource = readFileSync(resolve(root, 'src/app/admin/service-settings/page.tsx'), 'utf8');
const aiResourcesSource = readFileSync(resolve(root, 'src/app/admin/ai-resources/page.tsx'), 'utf8');

assert.match(
  plansSource,
  /grid gap-4 lg:grid-cols-2 xl:grid-cols-4/,
  'The four canonical packages must fit on one row at the primary PC breakpoint'
);

assert.match(
  accountsSource,
  /const \[loadError, setLoadError\][\s\S]*const \[actionError, setActionError\]/,
  'Account loading failures and account mutation failures must remain separate states'
);

assert.match(
  accountsSource,
  /setActionError\([\s\S]*role="alert"/,
  'Account mutation failures must stay visible inside the working surface'
);

assert.doesNotMatch(
  accountsSource,
  /setActionError\([\s\S]*window\.location\.reload\(\)/,
  'Account mutation failures must not force a full-page reload recovery path'
);

for (const [surface, source] of [
  ['accounts', accountsSource],
  ['subscriptions', subscriptionsSource],
]) {
  assert.match(
    source,
    /params\.set\('limit'[\s\S]*params\.set\('offset'[\s\S]*<ListPagination/,
    `${surface} directory must expose all filtered records through pagination`
  );
}

for (const [surface, source] of [
  ['packages', plansSource],
  ['credit packs', creditPacksSource],
  ['service settings', serviceSettingsSource],
  ['provider management', aiResourcesSource],
]) {
  assert.match(source, /role="alert"/, `${surface} errors must expose alert semantics`);
  assert.match(source, /role="status"[\s\S]*aria-live="polite"/, `${surface} success messages must expose polite status semantics`);
}
