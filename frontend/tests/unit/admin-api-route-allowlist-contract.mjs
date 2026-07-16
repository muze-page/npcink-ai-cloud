import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const sharedPath = resolve(process.cwd(), 'src/app/api/admin/_shared.ts');
const routeSource = readFileSync(routePath, 'utf8');
const sharedSource = readFileSync(sharedPath, 'utf8');

assert.match(
  sharedSource,
  /data: \{\},\s*meta: \{\s*trace_id: '',\s*revision: 'm6',?\s*\}/s,
  'allowlist failures must remain valid canonical API envelopes'
);

assert.match(
  routeSource,
  /if \(!routeResolution\) \{\s*return buildErrorResponse\(\s*404,\s*'proxy\.admin_route_not_allowed'/s,
  'unknown GET and write routes must return the explicit fail-closed response'
);

assert.doesNotMatch(
  routeSource,
  /runtime[\\/]retention[\\/]cleanup/,
  'dangerous runtime retention cleanup must not be exposed through the browser Admin proxy'
);

assert.match(
  routeSource,
  /pattern: \/\^accounts\\\/\[\^\/\]\+\\\/\(\?:credit-ledger\|subscription\)\$\/[\s\S]*?namespace: 'admin'[\s\S]*?requiredCapability: 'can_manage_billing'/,
  'a normal dynamic account credit-ledger read must resolve to its explicit admin route policy'
);

assert.match(
  routeSource,
  /pattern: \/\^accounts\\\/\[\^\/\]\+\\\/credit-ledger\\\/adjustments\$\/[\s\S]*?namespace: 'admin'/,
  'credit-ledger adjustments must use the backend admin namespace instead of a generic fallback'
);

assert.match(
  sharedSource,
  /session\.identity_type !== PLATFORM_ADMIN_IDENTITY_TYPE \|\|\s*session\.role !== PLATFORM_ADMIN_ROLE/s,
  'non-platform-admin identities must fail before any internal service request'
);

assert.match(
  sharedSource,
  /proxy\.admin_session_forbidden/,
  'wrong admin identity must return a stable forbidden error code'
);

assert.match(
  sharedSource,
  /session\.capabilities\?\.\[capability\] === true/,
  'route capability checks must fail closed unless the existing session capability is explicitly true'
);

assert.doesNotMatch(
  routeSource,
  /x-npcink-debug-portal-link/i,
  'the Admin proxy must not forward the Portal-only local-debug header'
);

console.log('admin_api_route_allowlist_contract: ok');
