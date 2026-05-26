import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const proxyPath = resolve(process.cwd(), 'src/proxy.ts');
const proxySource = readFileSync(proxyPath, 'utf8');

assert.match(
  proxySource,
  /const isDevelopment = process\.env\.NODE_ENV !== 'production';/,
  'proxy CSP must branch by NODE_ENV so development-only relaxations do not leak into production'
);
assert.match(
  proxySource,
  /if \(isDevelopment\) \{\s*scriptSrc\.push\("'unsafe-eval'"\);\s*\}/m,
  'proxy CSP must allow unsafe-eval only in development'
);
assert.doesNotMatch(
  proxySource,
  /script-src 'self' 'unsafe-eval' 'unsafe-inline'/,
  'proxy CSP must not hardcode unsafe-eval into production policy'
);
for (const directive of ["object-src 'none'", "base-uri 'self'", "frame-ancestors 'none'", "form-action 'self'"]) {
  assert.match(
    proxySource,
    new RegExp(directive.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    `proxy CSP must include ${directive}`
  );
}
