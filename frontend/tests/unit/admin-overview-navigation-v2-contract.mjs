import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const overview = readFileSync(resolve(process.cwd(), 'src/app/admin/page.tsx'), 'utf8');
const layout = readFileSync(resolve(process.cwd(), 'src/app/admin/layout.tsx'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

const quickLinksStart = overview.indexOf('const quickLinks = [');
const quickLinksEnd = overview.indexOf('const evidenceWindowMetrics', quickLinksStart);
assert.ok(quickLinksStart > 0 && quickLinksEnd > quickLinksStart, 'overview quick destinations must remain explicit');
const quickLinksSource = overview.slice(quickLinksStart, quickLinksEnd);
assert.equal(
  Array.from(quickLinksSource.matchAll(/href: '\/admin\//g)).length,
  4,
  'overview must expose only four canonical first-screen destinations'
);

assert.doesNotMatch(overview, /AdminWorkspaceSplit/, 'overview must not keep supporting evidence beside the primary work surface');
assert.doesNotMatch(overview, /secondaryActionHref|secondaryActionLabel/, 'overview header must keep one primary next action');
assert.match(
  overview,
  /<details[\s\S]*admin\.home_extended_evidence_title[\s\S]*items=\{evidenceWindowMetrics\}/,
  'runtime and usage snapshot must remain inside extended evidence'
);
assert.match(overview, /BackofficeDiagnosticNotice/, 'overview loading failure must remain scoped and retryable');
assert.match(overview, /BackofficeLayer[\s\S]*admin\.home_loading_desc/, 'overview loading state must preserve its route shell');
assert.match(overview, /setTimeout\(\(\) => controller\.abort\(\), 12000\)/, 'overview request must not remain loading indefinitely');
assert.match(overview, /overviewRuntimeAlertTitle\(overview\.runtimeTelemetry\.alerts\[0\], t\)/, 'overview watch items must localize known runtime alerts');
assert.match(overview, /overviewRuntimeAlertSummary\(alert, t\)/, 'overview evidence must localize known runtime summaries');

for (const route of [
  '/admin/plugin-observability',
  '/admin/media-observability',
  '/admin/vector-observability',
  '/admin/agent-feedback',
  '/admin/ai-advisor',
]) {
  assert.match(layout, new RegExp(`href: '${route}'`), `${route} must be discoverable in the quick switcher`);
}
assert.match(layout, /admin\.nav_group_diagnostics/, 'contextual diagnostic commands must share a Diagnostics group');
assert.match(i18n, /'admin\.home_loading_desc': '正在加载当前平台结论和运营队列。'/, 'overview loading copy must be localized');
assert.match(i18n, /'admin\.home_error_desc': '无法加载平台概览，系统未执行任何运营操作。'/, 'overview error copy must be localized');
