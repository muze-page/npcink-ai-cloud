import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const switcherSource = readFileSync(resolve(process.cwd(), 'src/components/ui/LocaleSwitcher.tsx'), 'utf8');
const localeContextSource = readFileSync(resolve(process.cwd(), 'src/contexts/LocaleContext.tsx'), 'utf8');

const localeOptionsMatch = i18nSource.match(/export const localeOptions:[\s\S]*?\];/);
assert.ok(localeOptionsMatch, 'localeOptions must be declared in i18n.ts');
const localeOptionsBlock = localeOptionsMatch[0];

assert.match(
  localeOptionsBlock,
  /value: 'en'/,
  'locale switcher must expose English'
);

assert.match(
  localeOptionsBlock,
  /value: 'zh-CN'/,
  'locale switcher must expose Simplified Chinese'
);

assert.doesNotMatch(
  localeOptionsBlock,
  /zh-TW|繁體中文/,
  'locale switcher must not expose Traditional Chinese while the product is bilingual-only'
);

assert.match(
  i18nSource,
  /export type Locale = 'en' \| 'zh-CN';/,
  'Locale type must stay bilingual-only until Traditional Chinese is restored completely'
);

assert.doesNotMatch(
  i18nSource,
  /^\s*'zh-TW': \{/m,
  'Traditional Chinese translation dictionary must be removed while the product is bilingual-only'
);

assert.doesNotMatch(
  i18nSource,
  /'language\.zh-TW'/,
  'Traditional Chinese language label must be removed while the product is bilingual-only'
);

assert.match(
  i18nSource,
  /if \(raw === 'zh-TW'\) \{\s*return 'zh-CN';\s*\}/,
  'stored Traditional Chinese locale must downgrade to Simplified Chinese'
);

assert.match(
  i18nSource,
  /normalized\.startsWith\('zh-tw'\)[\s\S]*?return 'zh-CN';/,
  'browser Traditional Chinese locale variants must resolve to Simplified Chinese'
);

assert.match(
  switcherSource,
  /localeOptions\.find\(\(l\) => l\.value === 'zh-CN'\)/,
  'locale switcher must render a Simplified Chinese fallback for stale locale state'
);

assert.match(
  i18nSource,
  /const normalizedLocale = resolveLocale\(locale\) \?\? DEFAULT_LOCALE;/,
  'persistLocale must normalize stale locale values before writing storage'
);

assert.match(
  localeContextSource,
  /const normalizedLocale = resolveLocale\(newLocale\) \?\? DEFAULT_LOCALE;/,
  'LocaleContext setLocale must normalize stale locale values before updating state'
);

console.log('locale_options_contract: ok');
