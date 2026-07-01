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
  /admin-shell[\s\S]*hidden w-60 flex-col[\s\S]*lg:pl-60/,
  'Admin layout must keep a compact desktop shell instead of the old wide sidebar'
);

assert.match(
  layoutSource,
  /<p className="sr-only">[\s\S]*t\(group\.descKey/,
  'Admin desktop sidebar should keep group descriptions available without rendering bulky helper text'
);

assert.match(
  layoutSource,
  /admin-nav-link flex w-full min-w-0[\s\S]*<span className="min-w-0 truncate">/,
  'Admin sidebar links must render as one full-width truncated row per item'
);

assert.match(
  layoutSource,
  /hidden items-center gap-2 md:flex[\s\S]*<LocaleSwitcher \/>[\s\S]*<ThemeToggle \/>/,
  'Admin desktop top bar must carry compact utility controls'
);

assert.doesNotMatch(
  layoutSource,
  /w-72|lg:pl-72|admin\.layout_boundary_desc|rounded-(?:2xl|lg) border border-blue-200/,
  'Admin layout must not regress to the wide explanatory sidebar shell or intro card'
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
