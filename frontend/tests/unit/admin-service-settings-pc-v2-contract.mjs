import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/service-settings/page.tsx'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(page, /const activeStateNotice = \(activeGroupDirty \|\| activeValidationIssues\.length > 0 \|\| error\)/, 'dirty, validation, and failure state must share one active-group notice');
for (const panel of ['portal', 'qq', 'email', 'payment']) {
  const start = page.indexOf(`id="service-settings-${panel}"`);
  assert.ok(start >= 0, `${panel} panel must exist`);
  const end = page.indexOf('</BackofficeSectionPanel>', start);
  const panelSource = page.slice(start, end);
  assert.match(panelSource, /\{activeStateNotice\}/, `${panel} feedback must stay inside its active panel`);
}

assert.match(page, /activeTab === 'portal' && activeGroupDirty[\s\S]*unsaved_short[\s\S]*activeTab === 'payment' && activeGroupDirty/, 'the active category tab must expose unsaved state');
assert.match(page, /onClick=\{restoreActiveGroup\}[\s\S]*restore_saved_values/, 'the local rollback action must clearly restore saved values');
assert.match(page, /data-ui="service-settings-high-risk"[\s\S]*payment_high_risk_title[\s\S]*payment_high_risk_desc/, 'payment credentials and callback identity must carry an explicit high-risk warning');
assert.match(page, /if \(loading && !data\)[\s\S]*AdminRouteSkeleton/, 'initial loading must preserve the admin route shell');
assert.match(page, /if \(!data\)[\s\S]*BackofficeDiagnosticNotice[\s\S]*onRetry=\{\(\) => void loadSettings\(\)\}/, 'initial failure must preserve the shell and retry only the bounded read');

for (const key of [
  'admin.service_settings.unsaved_short',
  'admin.service_settings.restore_saved_values',
  'admin.service_settings.load_shell_desc',
  'admin.service_settings.payment_high_risk_title',
  'admin.service_settings.payment_high_risk_desc',
]) {
  const occurrences = Array.from(i18n.matchAll(new RegExp(`'${key.replaceAll('.', '\\.')}':`, 'g'))).length;
  assert.equal(occurrences, 2, `${key} must exist in English and Simplified Chinese`);
}

console.log('admin_service_settings_pc_v2_contract: ok');
