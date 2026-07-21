import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const pageSource = readFileSync(
  fromFrontendRoot('src/app/admin/troubleshooting/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const troubleshootingKeys = Array.from(
  pageSource.matchAll(/(?:titleKey|descKey):\s*['`](admin\.[a-z0-9_.]+)['`]|t\(['`](admin\.troubleshooting\.[a-z0-9_.]+)['`]/g)
)
  .map((match) => match[1] || match[2])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

const workspaceKeys = [
  'admin.advanced.runtime_resolution_title',
  'admin.advanced.runtime_resolution_desc',
  'admin.advanced.capability_matrix_title',
  'admin.advanced.capability_matrix_desc',
  'admin.advanced.runtime_profiles_title',
  'admin.advanced.runtime_profiles_desc',
  'admin.advanced.recent_runtime_evidence_title',
  'admin.advanced.recent_runtime_evidence_desc',
  'admin.advanced.runtime_evidence_boundary',
  'admin.advanced.action_open_runtime_profiles',
];

const requiredKeys = [...new Set([...troubleshootingKeys, ...workspaceKeys])].sort();

assert.ok(
  troubleshootingKeys.length >= 35,
  'Runtime diagnostics workspace must declare localized copy for health, anomaly, inspector, and evidence states'
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
  /searchParams\.get\('window'\)[\s\S]*searchParams\.get\('focus'\)[\s\S]*recent_minutes: String\(windowHours \* 60\)/,
  'Runtime diagnostics must keep its time window and focused anomaly URL-addressable'
);

assert.match(
  pageSource,
  /runtime-diagnostic-issue[\s\S]*runtime-diagnostic-inspector[\s\S]*admin\.troubleshooting\.suggested_action[\s\S]*admin\.troubleshooting\.open_evidence/,
  'Runtime diagnostics must connect the anomaly queue to a focused read-only evidence inspector'
);

assert.match(
  pageSource,
  /evidenceLanes[\s\S]*id="evidence-lanes"[\s\S]*id="runtime-evidence"[\s\S]*admin\.advanced\.runtime_evidence_boundary/,
  'Narrow observability lanes and advanced runtime metadata must live under Runtime Diagnostics'
);

assert.match(
  pageSource,
  /createApiClient[\s\S]*`\/api\/admin\/runtime-telemetry\?\$\{params\.toString\(\)\}`[\s\S]*BackofficeSummaryStrip[\s\S]*providerCallRunCoverageRate[\s\S]*meteredRunCoverageRate/,
  'Runtime diagnostics must derive its conclusion and core metrics from the runtime telemetry source'
);

assert.doesNotMatch(
  pageSource,
  /advancedGroups|activeGroupKey|group_filter_label|Choose an evidence lane/,
  'Runtime diagnostics must not keep a fake one-group catalog filter or static first-entry focus'
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
