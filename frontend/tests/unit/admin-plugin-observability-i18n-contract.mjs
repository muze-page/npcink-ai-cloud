import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/plugin-observability/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const pluginKeys = Array.from(
  pageSource.matchAll(/['`](admin\.plugin_(?:obs|observability)[a-z0-9_.]*)['`]/g)
)
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

const requiredDynamicKeys = [
  'admin.plugin_obs_period_daily',
  'admin.plugin_obs_period_weekly',
  'admin.plugin_obs_workflow_active',
  'admin.plugin_obs_workflow_acknowledged',
  'admin.plugin_obs_workflow_muted',
  'admin.plugin_obs_workflow_resolved',
  'admin.plugin_obs_severity_error',
  'admin.plugin_obs_severity_warning',
  'admin.plugin_obs_attention_title_inactive',
  'admin.plugin_obs_attention_detail_inactive',
  'admin.plugin_obs_attention_action_inactive',
  'admin.plugin_obs_attention_title_error_rate_high',
  'admin.plugin_obs_attention_detail_error_rate_high',
  'admin.plugin_obs_attention_action_error_rate_high',
  'admin.plugin_obs_attention_title_error_rate_elevated',
  'admin.plugin_obs_attention_detail_error_rate_elevated',
  'admin.plugin_obs_attention_action_error_rate_elevated',
  'admin.plugin_obs_attention_title_latency_high',
  'admin.plugin_obs_attention_detail_latency_high',
  'admin.plugin_obs_attention_action_latency_high',
  'admin.plugin_obs_attention_title_reporting_stale',
  'admin.plugin_obs_attention_detail_reporting_stale',
  'admin.plugin_obs_attention_action_reporting_stale',
  'admin.plugin_obs_attention_title_plugin_error',
  'admin.plugin_obs_attention_detail_plugin_error',
  'admin.plugin_obs_attention_action_plugin_error',
  'admin.plugin_obs_attention_title_catalog_churn',
  'admin.plugin_obs_attention_detail_catalog_churn',
  'admin.plugin_obs_attention_action_catalog_churn',
  'admin.plugin_obs_attention_title_plugin_missing',
  'admin.plugin_obs_attention_detail_plugin_missing',
  'admin.plugin_obs_attention_action_plugin_missing',
  'admin.plugin_obs_attention_title_top_error',
  'admin.plugin_obs_attention_detail_top_error',
  'admin.plugin_obs_attention_action_top_error',
].sort();

const requiredKeys = [...pluginKeys, ...requiredDynamicKeys]
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(
  requiredKeys.length > 80,
  'Plugin Observability page must route visible copy through plugin observability i18n keys'
);

for (const key of requiredKeys) {
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
  i18nSource,
  /'admin\.plugin_observability_title': '插件观测'/,
  'Plugin Observability must provide a Simplified Chinese page title'
);

assert.match(
  i18nSource,
  /'admin\.plugin_obs_attention_scope_notice': '关注项状态只属于 Cloud 显示层/,
  'Plugin Observability must explain that attention state is Cloud display state only'
);

assert.match(
  pageSource,
  /npcink-cloud-addon/,
  'Plugin Observability filters must include the Cloud Addon telemetry source'
);

assert.doesNotMatch(
  pageSource,
  /detail:\s*data\.health\.summary/,
  'Plugin Observability must not render backend English health summary directly'
);

assert.doesNotMatch(
  pageSource,
  /\{item\.(title|detail|suggestedAction)\}/,
  'Plugin Observability must not render backend English attention copy directly'
);

assert.doesNotMatch(
  pageSource,
  />\s*(Filter|Ack|Mute 24h|Resolve|Clear state|All codes)\s*</,
  'Plugin Observability controls must use localized labels'
);
