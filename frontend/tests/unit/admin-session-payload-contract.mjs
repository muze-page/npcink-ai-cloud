import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const sharedPath = resolve(process.cwd(), 'src/app/api/admin/_shared.ts');
const source = readFileSync(sharedPath, 'utf8');

assert.match(
  source,
  /principal_id: string;/,
  'admin session payload must expose the principal_id identity contract'
);

assert.match(
  source,
  /String\(data\?\.principal_id \|\| ''\)\.trim\(\)/,
  'admin session parser must require the canonical principal_id'
);

assert.doesNotMatch(
  source,
  /platform_admin_ref/,
  'admin session payload must not retain the retired platform_admin_ref alias or fallback'
);

assert.match(
  source,
  /Object\.entries\(data\.capabilities as Record<string, unknown>\)[\s\S]*?key,\s*value === true/,
  'admin capability parsing must only accept a literal boolean true'
);

assert.doesNotMatch(
  source,
  /Boolean\(value\)/,
  'string and numeric capability values must not be coerced to true'
);

for (const retiredHelper of [
  'requireAdminSession',
  'proxyAdminServiceGet',
  'proxyAdminServiceJsonPost',
  'proxyAdminJsonPost',
]) {
  assert.doesNotMatch(
    source,
    new RegExp(`export async function ${retiredHelper}\\b`),
    `${retiredHelper} must remain deleted after its consumers are removed`
  );
}

assert.doesNotMatch(
  source,
  /error instanceof Error \? error\.message/,
  'admin session verification must not expose internal network exception details'
);

console.log('admin_session_payload_contract: ok');
