import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const sharedPath = resolve(process.cwd(), 'src/app/api/admin/_shared.ts');
const source = readFileSync(routePath, 'utf8');
const sharedSource = readFileSync(sharedPath, 'utf8');

assert.match(
  sharedSource,
  /status: 'error',[\s\S]*?error_code: errorCode,[\s\S]*?message,[\s\S]*?data: \{\},[\s\S]*?meta: \{\s*trace_id: '',\s*revision: 'm6'/,
  'BFF errors must use the canonical Cloud envelope consumed by ApiClient'
);

assert.doesNotMatch(
  sharedSource,
  /message,\s*revision: 'm6'/,
  'BFF errors must not keep revision at the envelope top level'
);

assert.match(
  source,
  /const ADMIN_ROUTE_RULES: readonly AdminRouteRule\[\] = \[/,
  'admin proxy must declare one explicit method and path policy table'
);

assert.match(
  source,
  /pattern: \/\^audit-events\(\?:\\\/summary\)\?\$\/[\s\S]*?namespace: 'service'/,
  'audit event reads must use the backend service-plane evidence endpoint'
);

assert.doesNotMatch(
  source,
  /if \(method !== 'GET'\)\s*{\s*const sessionResult = await requireAdminSessionData\(request\);/s,
  'admin proxy must not skip session validation for GET requests'
);

assert.match(
  source,
  /const sessionResult = await requireAdminSessionData\(request\);\s*if \(sessionResult instanceof NextResponse\)/,
  'admin proxy must validate the backend admin session before forwarding any method'
);

assert.match(
  source,
  /ADMIN_IDEMPOTENCY_KEY_PATTERN[\s\S]*resolveAdminIdempotencyKey[\s\S]*createAdminIdempotencyKey/,
  'admin proxy must sanitize or replace invalid write idempotency keys before forwarding to backend'
);

assert.doesNotMatch(
  source,
  /'idempotency-key',/,
  'admin proxy must not copy raw idempotency-key as a generic forwarded header'
);

assert.match(
  source,
  /pattern: \/\^accounts\\\/\[\^\/\]\+\\\/subscription\(\?:\\\/\(\?:suspend\|cancel\)\)\?\$\//,
  'admin account subscription writes must route to the backend admin service namespace'
);

assert.match(
  source,
  /rule\.namespace === 'admin' \? '\/internal\/service\/admin' : '\/internal\/service'/,
  'admin route resolution must preserve the declared backend namespace'
);

assert.match(
  source,
  /methods: \['PATCH'\],[\s\S]*?pattern: \/\^service-settings\\\/\(\?:portal-public\|qq-login\|email\|alipay-payment\)\$\/[\s\S]*?methods: \['POST'\],[\s\S]*?pattern: \/\^service-settings\\\/\(\?:qq-login\\\/test\|email\\\/test\|email\\\/preview\|alipay-payment\\\/test\)\$\//,
  'admin service-settings writes must enumerate the supported method for each subpath'
);

assert.doesNotMatch(
  source,
  /audio-providers/,
  'admin proxy must not expose the retired env-backed audio provider settings routes'
);

assert.doesNotMatch(
  source,
  /web-search-providers|image-source-providers/,
  'admin proxy must not expose retired env-backed capability provider settings routes'
);

assert.doesNotMatch(
  source,
  /audio-jobs/,
  'the browser admin proxy must not expose internal audio job routes without a browser consumer'
);

assert.doesNotMatch(
  source,
  /normalized === 'ai-resources\/profile-preferences'[\s\S]*?return '\/internal\/service\/admin\/ai-resources\/profile-preferences';/,
  'admin proxy must not expose the retired AI resource profile-preferences route'
);

assert.match(
  source,
  /methods: \['GET'\],[\s\S]*?pattern: \/\^\(\?:ai-resources\|provider-connections\|model-references\|site-knowledge-vector-profile\|runtime-profiles\)\$\/[\s\S]*?namespace: 'admin'[\s\S]*?requiredCapability: 'can_manage_catalog'/,
  'hosted runtime profiles must expose one exact can_manage_catalog GET route'
);

assert.match(
  source,
  /methods: \['PUT'\],[\s\S]*?pattern: \/\^runtime-profiles\$\/[\s\S]*?namespace: 'admin'[\s\S]*?requiredCapability: 'can_manage_catalog'/,
  'hosted runtime profiles must expose one exact can_manage_catalog PUT route'
);

assert.doesNotMatch(
  source,
  /ability-models/,
  'admin proxy must fail closed for every retired ability-model endpoint'
);

assert.equal(
  source.match(/runtime-profiles/g)?.length,
  2,
  'hosted runtime profiles must only appear in the exact GET and PUT rules so every other method fails closed'
);

assert.match(
  source,
  /provider-connections\\\/preview-catalog/,
  'provider connection catalog previews must route through the backend admin service namespace'
);

assert.match(
  source,
  /pattern: \/\^subscriptions\\\/\[\^\/\]\+\\\/topup\$\//,
  'subscription top-up writes must route to the service top-up endpoint'
);

assert.doesNotMatch(
  source,
  /return normalized \? `\/internal\/service\/\$\{normalized\}` : '\/internal\/service';/,
  'admin proxy must not retain a default internal-service write pass-through'
);

assert.doesNotMatch(
  source,
  /return normalized \? `\/admin\/\$\{normalized\}` : '\/admin';/,
  'admin write proxy must not forward to the missing backend /admin root'
);

assert.match(
  source,
  /proxy\.admin_route_not_allowed/,
  'unknown admin routes must fail closed before receiving the internal token'
);

assert.match(
  source,
  /requireAdminCapability\(\s*sessionResult\.session,\s*routeResolution\.requiredCapability/s,
  'declared admin route capabilities must be enforced against the verified session'
);

assert.doesNotMatch(
  source,
  /x-npcink-debug-portal-link/i,
  'admin proxy must not forward the Portal local-debug header'
);

assert.match(
  source,
  /catch \{\s*return buildErrorResponse\(\s*502,\s*options\.unreachableCode,\s*options\.unreachableMessage\s*\)/s,
  'admin proxy must return a stable public error without exposing network exception details'
);

assert.doesNotMatch(
  source,
  /error instanceof Error \? error\.message : options\.unreachableMessage/,
  'admin proxy must not expose internal fetch error messages to the browser'
);

console.log('admin_api_proxy_contract: ok');
