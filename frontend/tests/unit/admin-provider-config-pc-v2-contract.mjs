import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/ai-resources/page.tsx'), 'utf8');
const directory = readFileSync(resolve(process.cwd(), 'src/components/admin/SupplierConnectionTables.tsx'), 'utf8');
const dialog = readFileSync(resolve(process.cwd(), 'src/components/admin/ProviderConnectionDialog.tsx'), 'utf8');
const i18n = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(page, /<ModelSupplierTable[\s\S]*testingConnectionId=\{testingConnectionId\}[\s\S]*onTest=\{\(connectionId\) => void runProviderConnectionTest\(connectionId\)\}/, 'model suppliers must expose the same bounded test flow as capability suppliers');
assert.match(directory, /selectedTestResult\?\.ok[\s\S]*role="status"[\s\S]*test_result_passed_inline/, 'successful supplier tests must render beside the selected supplier');
assert.match(directory, /selectedTestResult && !selectedTestResult\.ok[\s\S]*role="alert"/, 'failed supplier tests must render beside the selected supplier');
assert.match(directory, /selectedIsConfirmingDelete[\s\S]*role="alert"[\s\S]*delete_confirmation_notice/, 'delete confirmation must state impact in the selected supplier inspector');

assert.match(dialog, /document\.body\.style\.overflow = 'hidden'/, 'provider configuration must prevent background scroll');
assert.match(dialog, /event\.key === 'Escape'[\s\S]*onCloseRef\.current\(\)/, 'provider configuration must close with Escape while idle');
assert.match(dialog, /event\.key !== 'Tab'[\s\S]*first[\s\S]*last[\s\S]*\.focus\(\)/, 'provider configuration must contain keyboard focus');
assert.match(dialog, /previouslyFocused\?\.focus\(\)/, 'provider configuration must restore the invoking control');
assert.match(dialog, /aria-describedby=\{`\$\{titleId\}-workflow-notice`\}/, 'save-and-test behavior must be associated with the dialog');

assert.match(page, /if \(loading\)[\s\S]*AdminRouteSkeleton/, 'provider loading must preserve the admin route shell');
assert.match(page, /BackofficeDiagnosticNotice[\s\S]*onRetry=\{\(\) => void loadResources\(\)\}/, 'provider initial failure must offer bounded retry');

for (const key of [
  'admin.ai_resources.test_result_passed_inline',
  'admin.ai_resources.delete_confirmation_notice',
]) {
  assert.ok(i18n.includes(`'${key}':`), `${key} must have Simplified Chinese operator copy`);
}

console.log('admin_provider_config_pc_v2_contract: ok');
