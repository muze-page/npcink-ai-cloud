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
const providerDialogSource = readFileSync(resolve(root, 'src/components/admin/ProviderConnectionDialog.tsx'), 'utf8');
const toastSource = readFileSync(resolve(root, 'src/components/ui/Toast.tsx'), 'utf8');

assert.match(
  plansSource,
  /grid gap-4 lg:grid-cols-2 2xl:grid-cols-4/,
  'The collapsed package-initialization utility must fit the four canonical packages on one row at wide PC breakpoints'
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
]) {
  assert.match(source, /role="alert"/, `${surface} errors must expose alert semantics`);
  assert.match(source, /role="status"[\s\S]*aria-live="polite"/, `${surface} success messages must expose polite status semantics`);
}

assert.match(
  serviceSettingsSource,
  /role=\{error \|\| activeValidationIssues\.length > 0 \? 'alert' : 'status'\}/,
  'service settings validation and request errors must expose alert semantics'
);
assert.match(
  serviceSettingsSource,
  /useToast\(\)[\s\S]*showSuccessToast/,
  'service settings success feedback must use the global Toast live region without shifting the form layout'
);

assert.match(
  providerDialogSource,
  /role="alert"[\s\S]*\{error\}/,
  'provider form errors must expose alert semantics in the active dialog'
);
assert.match(
  providerDialogSource,
  /role="status"[\s\S]*aria-live="polite"[\s\S]*\{message\}/,
  'provider form success and progress messages must expose polite status semantics in the active dialog'
);
assert.match(
  toastSource,
  /role=\{toast\.type === 'error' \|\| toast\.type === 'warning' \? 'alert' : 'status'\}[\s\S]*aria-live=\{toast\.type === 'error' \|\| toast\.type === 'warning' \? 'assertive' : 'polite'\}/,
  'provider page transient Toast feedback must preserve severity-appropriate live-region semantics'
);
