import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const currencySource = readFileSync(resolve(frontendRoot, 'src/lib/currency.ts'), 'utf8');

assert.match(
  currencySource,
  /export const ADMIN_CURRENCY = DEFAULT_CURRENCY/,
  'Admin currency must use the shared default platform currency'
);

assert.match(
  currencySource,
  /formatAdminCurrency[\s\S]*from: ADMIN_CURRENCY[\s\S]*to: ADMIN_CURRENCY/,
  'Admin currency formatter must treat incoming admin amounts as CNY, not convert them from USD'
);
