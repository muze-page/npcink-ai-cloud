import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const runtimeProfilesPagePath = resolve(process.cwd(), 'src/app/admin/runtime-profiles/page.tsx');
const standaloneWorkbenchPath = resolve(process.cwd(), 'src/app/admin/audio-workbench/page.tsx');
const retiredAbilityModelsPagePath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');
const adminProxyPath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const troubleshootingPath = resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');

const runtimeProfilesSource = readFileSync(runtimeProfilesPagePath, 'utf8');
const adminProxySource = readFileSync(adminProxyPath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const troubleshootingSource = readFileSync(troubleshootingPath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');

assert.equal(existsSync(standaloneWorkbenchPath), false, 'the standalone audio workbench must remain removed');
assert.equal(existsSync(retiredAbilityModelsPagePath), false, 'the retired ability-model workspace must not remain as a parallel page');

assert.doesNotMatch(
  runtimeProfilesSource,
  /audio-jobs|audio workbench|audio preview|createAudioPreview|inspector_tab_preview/i,
  'hosted runtime profiles must not consume or reproduce the audio workbench'
);

assert.doesNotMatch(
  adminProxySource,
  /audio-jobs/,
  'the browser admin proxy must not expose internal audio job routes after the visible workbench is removed'
);

assert.match(
  adminProxySource,
  /if \(!routeResolution\) \{\s*return buildErrorResponse\(\s*404,\s*'proxy\.admin_route_not_allowed'/s,
  'unknown browser admin routes must remain inside the fail-closed policy'
);

for (const [source, label] of [
  [layoutSource, 'admin navigation'],
  [troubleshootingSource, 'advanced troubleshooting'],
  [i18nSource, 'i18n copy'],
]) {
  assert.doesNotMatch(source, /\/admin\/audio-workbench|action_open_audio_workbench|nav_audio_workbench/, `${label} must not expose the retired audio workbench`);
}

console.log('admin_audio_workbench_contract: ok');
