import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const portalSharedPath = resolve(process.cwd(), 'src/app/api/portal/_shared.ts');
const portalRoutePath = resolve(process.cwd(), 'src/app/api/portal/[...path]/route.ts');
const adminSharedPath = resolve(process.cwd(), 'src/app/api/admin/_shared.ts');
const proxyPath = resolve(process.cwd(), 'src/proxy.ts');

const portalSharedSource = readFileSync(portalSharedPath, 'utf8');
const portalRouteSource = readFileSync(portalRoutePath, 'utf8');
const adminSharedSource = readFileSync(adminSharedPath, 'utf8');
const proxySource = readFileSync(proxyPath, 'utf8');

for (const headerName of [
  'authorization',
  'idempotency-key',
  'x-npcink-debug-portal-link',
  'x-npcink-portal-member-ref',
  'x-npcink-portal-token',
]) {
  assert.match(
    portalSharedSource,
    new RegExp(`['"]${headerName}['"]`),
    `portal proxy must preserve ${headerName}`
  );
}

assert.match(
  portalSharedSource,
  /encodeURIComponent\(segment\)/,
  'portal catch-all proxy must encode path segments before forwarding'
);
assert.match(
  portalSharedSource,
  /return normalized \? `\/portal\/v1\/\$\{normalized\}` : '\/portal\/v1';/,
  'portal catch-all proxy must forward into /portal/v1'
);
assert.match(
  portalSharedSource,
  /if \(contentType\) \{\s*headers\['Content-Type'\] = contentType;\s*\}/m,
  'portal proxy must forward content-type for non-GET requests'
);
assert.match(
  portalSharedSource,
  /body = await request\.text\(\);/,
  'portal proxy must forward raw request bodies'
);

for (const method of ['GET', 'POST', 'PUT', 'DELETE']) {
  assert.match(
    portalRouteSource,
    new RegExp(`export async function ${method}`),
    `portal catch-all route must export ${method}`
  );
}
assert.match(
  portalRouteSource,
  /proxyPortalPathSegments\(request, path \|\| \[\], \{/,
  'portal catch-all route must delegate to the shared proxy helper'
);

for (const headerName of ['Cookie', 'Origin', 'Referer']) {
  assert.match(
    adminSharedSource,
    new RegExp(`headers\\.${headerName}|headers\\['${headerName}'\\]`),
    `forwarded admin headers must include ${headerName}`
  );
}

assert.match(
  adminSharedSource,
  /firstHeaderValue\(request\.headers\.get\('x-forwarded-host'\)\)/,
  'admin proxy must prefer the forwarded browser host from the trusted edge proxy'
);
assert.match(
  adminSharedSource,
  /firstHeaderValue\(request\.headers\.get\('x-forwarded-proto'\)\)/,
  'admin proxy must prefer the forwarded browser proto from the trusted edge proxy'
);
assert.match(
  adminSharedSource,
  /request\.headers\.get\('x-forwarded-host'\)/,
  'admin proxy must read forwarded host from the trusted edge proxy headers'
);
assert.match(
  portalSharedSource,
  /const requestHost = getExternalRequestHost\(request\);/,
  'portal proxy must preserve the external host instead of collapsing to an internal Next host'
);

assert.match(
  proxySource,
  /loginUrl\.searchParams\.set\('redirect', `\$\{pathname\}\$\{request\.nextUrl\.search\}`\)/,
  'portal page auth redirect must preserve query parameters such as WordPress addon connection state'
);
