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
  /data\?\.principal_id \|\| data\?\.platform_admin_ref/,
  'admin session parser must accept principal_id with platform_admin_ref fallback'
);

assert.match(
  source,
  /data\?\.platform_admin_ref \|\| principalId/,
  'admin session parser must preserve platform_admin_ref as a compatibility alias'
);

console.log('admin_session_payload_contract: ok');
