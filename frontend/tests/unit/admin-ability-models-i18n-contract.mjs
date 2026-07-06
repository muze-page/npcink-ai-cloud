import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

import { fromFrontendRoot } from './_paths.mjs';

const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const zhSource = i18nSource.slice(zhStart);

const requiredChineseCopy = [
  "'admin.ai_resources.ability_model_dialog_title': '配置能力模型路由'",
  "'admin.ai_resources.ability_model_dialog_desc': '这会更新一条共享的 Cloud 运行时路由。插件开关、prompt、审批和最终写入不会改变。'",
  "'admin.ai_resources.ability_model_primary_model': '主模型'",
  "'admin.ai_resources.ability_model_fallback_model': '兜底模型'",
  "'admin.ai_resources.ability_model_unassigned': '未分配'",
  "'admin.ai_resources.ability_model_region_global': '全球'",
  "'admin.ai_resources.ability_model_save_notice': '保存后会更新此能力路由使用的 Cloud 运行时配置绑定。'",
];

for (const expectedCopy of requiredChineseCopy) {
  assert.ok(
    zhSource.includes(expectedCopy),
    `Ability-model routing dialog must provide Simplified Chinese copy: ${expectedCopy}`
  );
}

assert.doesNotMatch(
  zhSource,
  /Configure ability-model route|PRIMARY MODEL|FALLBACK MODEL|Unassigned|Saving updates the Cloud runtime profile binding/,
  'Ability-model routing dialog must not fall back to visible English copy in Simplified Chinese'
);

console.log('admin_ability_models_i18n_contract: ok');
