import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const layoutSource = readFileSync(fromFrontendRoot('src/app/admin/layout.tsx'), 'utf8');
const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
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
  /createApiClient[\s\S]*\.request\('\/admin\/session'\)[\s\S]*setAdminSessionReady\(true\)[\s\S]*window\.location\.replace\(`\/admin\/login\?redirect=/,
  'Admin layout must validate the session before showing protected navigation'
);
assert.match(
  layoutSource,
  /if \(!adminSessionReady\) \{[\s\S]*return <LoadingFallback \/>;/,
  'Admin layout must keep the navigation hidden while session validation is pending'
);

assert.match(
  layoutSource,
  /ADMIN_SIDEBAR_STORAGE_KEY[\s\S]*sidebarCollapsed[\s\S]*w-16[\s\S]*w-60[\s\S]*lg:pl-16[\s\S]*lg:pl-60/,
  'Admin layout must support a persistent collapsible desktop sidebar'
);

assert.match(
  layoutSource,
  /key === 'b'[\s\S]*setSidebarCollapsed[\s\S]*key === 'k'[\s\S]*setCommandOpen/,
  'Admin layout must expose keyboard shortcuts for sidebar and quick switching'
);

assert.match(
  layoutSource,
  /admin\.command_open[\s\S]*admin\.command_title[\s\S]*filteredCommandItems/,
  'Admin layout must expose a bounded quick switcher for existing admin routes'
);

assert.match(
  layoutSource,
  /<p className="sr-only">[\s\S]*t\(group\.descKey/,
  'Admin desktop sidebar should keep group descriptions available without rendering bulky helper text'
);

assert.match(
  layoutSource,
  /admin-nav-link flex w-full min-w-0[\s\S]*min-w-0 truncate/,
  'Admin sidebar links must render as one full-width truncated row per item'
);

assert.match(
  layoutSource,
  /hidden items-center gap-2 md:flex[\s\S]*<LocaleSwitcher \/>[\s\S]*<ThemeToggle \/>/,
  'Admin desktop top bar must carry compact utility controls'
);

const desktopAsideStart = layoutSource.indexOf('<aside');
const desktopAsideEnd = layoutSource.indexOf('</aside>', desktopAsideStart);
const desktopAsideSource = layoutSource.slice(desktopAsideStart, desktopAsideEnd);

assert.ok(
  desktopAsideStart >= 0 && desktopAsideEnd > desktopAsideStart,
  'Admin layout must keep a desktop sidebar boundary for navigation contracts'
);

assert.doesNotMatch(
  desktopAsideSource,
  /href="\/portal"/,
  'Admin desktop sidebar must not include a Portal shortcut; cross-surface links belong in the top bar or mobile drawer'
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
