import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const panelSource = readFileSync(
  resolve(root, 'src/components/portal/PortalPluginMonitoringPanel.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(root, 'src/lib/i18n.ts'), 'utf8');

assert.match(
  panelSource,
  /function customerAttentionCopy[\s\S]*plugin_observability\.inactive[\s\S]*plugin_observability\.top_error/,
  'Portal plugin monitoring must map stable diagnostic codes to customer-readable copy'
);
assert.doesNotMatch(
  panelSource,
  />\{item\.title\}<|>\{item\.detail\}<|\{item\.suggested_action\}/,
  'Portal plugin monitoring must not render raw backend English diagnostic prose'
);
assert.match(
  panelSource,
  /customerHealthSummary\(health\.status, t\)[\s\S]*digestHeadline[\s\S]*digestBullets/,
  'Portal plugin monitoring health and digest must use localized customer copy'
);
assert.match(
  i18nSource,
  /'portal\.monitoring\.attention_inactive_title': 'No recent connection activity'[\s\S]*'portal\.monitoring\.attention_inactive_title': '近期没有连接活动'/,
  'Portal monitoring customer copy must be localized in English and Chinese'
);

console.log('portal_monitoring_customer_copy_contract: ok');
