import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const pageSource = readFileSync(resolve(root, 'src/app/admin/credit-packs/page.tsx'), 'utf8');
const proxySource = readFileSync(resolve(root, 'src/app/api/admin/[...path]/route.ts'), 'utf8');

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
  /data-ui="credit-pack-directory-item"[\s\S]*id="credit-pack-inspector"[\s\S]*<Modal/,
  'Admin credit pack page must render a read-first directory, contextual inspector, and one-pack editor'
);
assert.doesNotMatch(
  pageSource,
  /overflow-x-auto[\s\S]*min-w-\[980px\]|grid-cols-\[1\.2fr_0\.8fr_0\.8fr_0\.7fr_1\.2fr_0\.4fr\]/,
  'Admin credit pack page must not regress to the wide horizontal table layout'
);
assert.match(
  pageSource,
  /ADMIN_CURRENCY/,
  'Admin credit pack page must use the shared admin CNY currency constant'
);
assert.doesNotMatch(
  pageSource,
  /<option value="USD">|onChange=\{\(event\) => updateItem\(item\.pack_id, \{ currency:/,
  'Admin credit pack page must not let operators switch customer pack pricing away from RMB'
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
  /methods: \['PATCH'\],[\s\S]*?pattern: \/\^credit-packs\$\/[\s\S]*?namespace: 'admin'[\s\S]*?requiredCapability: 'can_manage_catalog'/,
  'Admin proxy must explicitly allowlist credit pack writes in the admin namespace with catalog authority'
);
