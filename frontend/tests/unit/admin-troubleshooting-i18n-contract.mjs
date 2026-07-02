import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const troubleshootingKeys = Array.from(
  pageSource.matchAll(/(?:titleKey|descKey|actionKey|groupKey):\s*['`](admin\.[a-z0-9_.]+)['`]/g)
)
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

const workspaceKeys = [
  'admin.advanced.mode',
  'admin.advanced.read_only',
  'admin.advanced.catalog_eyebrow',
  'admin.advanced.catalog_title',
  'admin.advanced.group_filter_label',
  'admin.advanced.all_groups',
  'admin.advanced.all_groups_desc',
  'admin.advanced.visible_entries',
  'admin.advanced.inspector_eyebrow',
  'admin.advanced.inspector_title',
  'admin.advanced.inspector_desc',
  'admin.advanced.suggested_first_step',
  'admin.advanced.boundary_note',
  'admin.advanced.runtime_evidence_eyebrow',
  'admin.advanced.runtime_evidence_scope',
  'admin.advanced.runtime_resolution_title',
  'admin.advanced.runtime_resolution_desc',
  'admin.advanced.capability_matrix_title',
  'admin.advanced.capability_matrix_desc',
  'admin.advanced.runtime_profiles_title',
  'admin.advanced.runtime_profiles_desc',
  'admin.advanced.recent_runtime_evidence_title',
  'admin.advanced.recent_runtime_evidence_desc',
  'admin.advanced.runtime_evidence_boundary',
  'admin.advanced.action_open_model_binding',
  'admin.advanced.group_runtime_desc',
  'admin.advanced.group_governance_desc',
];

const requiredKeys = [...new Set([...troubleshootingKeys, ...workspaceKeys])].sort();

assert.ok(
  troubleshootingKeys.length >= 17,
  'Advanced troubleshooting cards must declare i18n keys for title, description, action, and group copy'
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
  pageSource,
  /useState<string>\('all'\)[\s\S]*role="tablist"[\s\S]*aria-selected=\{activeGroupKey === 'all'\}/,
  'Advanced troubleshooting should present a compact diagnostic group filter'
);

assert.match(
  pageSource,
  /admin\.advanced\.inspector_title[\s\S]*admin\.advanced\.suggested_first_step[\s\S]*admin\.advanced\.boundary_note/,
  'Advanced troubleshooting should keep a right-side read-only focus inspector'
);

assert.match(
  pageSource,
  /runtimeEvidenceItems[\s\S]*id="runtime-evidence"[\s\S]*admin\.advanced\.runtime_evidence_boundary/,
  'Runtime resolution, capability matrix, runtime configurations, and recent evidence must live under Runtime Diagnostics'
);

assert.doesNotMatch(
  pageSource,
  /createCheckout|paymentIntent|invoice_create|wordpress_write|auto_apply|publish_to_wordpress|registerAbility|workflowRegistry|routerEditor|promptEditor/,
  'Advanced troubleshooting must remain a read-only evidence catalog, not a mutation or control-plane surface'
);

assert.match(
  i18nSource,
  /'admin\.nav_agent_feedback': 'Agent 反馈质量'/,
  'Agent Feedback advanced card title must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.advanced\.action_view_agent_feedback': '查看质量反馈'/,
  'Agent Feedback advanced card action must provide Simplified Chinese copy'
);
