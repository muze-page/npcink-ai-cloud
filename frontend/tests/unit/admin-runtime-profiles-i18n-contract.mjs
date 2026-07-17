import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

import { fromFrontendRoot } from './_paths.mjs';

const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
const pageSource = readFileSync(fromFrontendRoot('src/app/admin/runtime-profiles/page.tsx'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);
const pageKeys = [...pageSource.matchAll(/copy\('([^']+)'/g)].map((match) => match[1]);

assert.ok(pageKeys.length > 0, 'hosted runtime profiles must declare localized operator copy');
for (const key of new Set(pageKeys)) {
  const pattern = new RegExp(`'admin\\.runtime_profiles\\.${key.replaceAll('.', '\\.')}':`);
  assert.match(enSource, pattern, `admin.runtime_profiles.${key} must exist in English translations`);
  assert.match(zhSource, pattern, `admin.runtime_profiles.${key} must exist in Simplified Chinese translations`);
}

assert.doesNotMatch(
  i18nSource,
  /admin\.nav_ability_models|admin\.ai_resources\.ability_model_|配置能力模型路由|Configure ability-model route/,
  'visible localization must not retain the retired ability-model workspace'
);

console.log('admin_runtime_profiles_i18n_contract: ok');
