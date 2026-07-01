import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const layoutSource = readFileSync(resolve(process.cwd(), 'src/app/admin/layout.tsx'), 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const layoutKeys = Array.from(
  layoutSource.matchAll(/(?:labelKey|groupKey|descKey):\s*['`]([a-z0-9_.-]+)['`]/g)
)
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(
  layoutKeys.length >= 15,
  'Admin layout must declare grouped nav i18n keys for sidebar labels and descriptions'
);

for (const key of layoutKeys) {
  assert.match(
    enSource,
    new RegExp(`'${key.replaceAll('.', '\\.')}':`),
    `${key} must exist in the English translation dictionary`
  );
  assert.match(
    zhSource,
    new RegExp(`'${key.replaceAll('.', '\\.')}':`),
    `${key} must exist in the Simplified Chinese translation dictionary`
  );
}

assert.match(
  layoutSource,
  /admin-primary-nav/,
  'Admin layout must keep the stable admin-primary-nav selector for e2e checks'
);

assert.match(
  layoutSource,
  /admin\.nav_group_customer_service/,
  'Admin layout must expose a customer and service sidebar group'
);

assert.match(
  layoutSource,
  /admin\.nav_group_runtime_ops/,
  'Admin layout must expose a runtime sidebar group'
);

assert.doesNotMatch(
  layoutSource,
  /Provider Management|Ability-Model Routing/,
  'Admin layout fallbacks should use boundary-safe runtime copy'
);
