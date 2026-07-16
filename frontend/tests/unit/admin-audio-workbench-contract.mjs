import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const workbenchPagePath = resolve(process.cwd(), 'src/app/admin/audio-workbench/page.tsx');
const adminProxyPath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const abilityModelsPagePath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const troubleshootingPath = resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');

const adminProxySource = readFileSync(adminProxyPath, 'utf8');
const abilityModelsPageSource = readFileSync(abilityModelsPagePath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const troubleshootingSource = readFileSync(troubleshootingPath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');

assert.equal(
  existsSync(workbenchPagePath),
  false,
  'standalone /admin/audio-workbench page must be removed; audio preview belongs inside ability-model routing'
);

assert.match(
  adminProxySource,
  /methods: \['POST'\],[\s\S]*?pattern: \/\^audio-jobs\$\/[\s\S]*?namespace: 'admin'[\s\S]*?requiredCapability: 'can_manage_catalog'/,
  'audio job creation must remain explicitly allowlisted for the ability-model routing dialog preview'
);

assert.match(
  adminProxySource,
  /if \(!routeResolution\) \{\s*return buildErrorResponse\(\s*404,\s*'proxy\.admin_route_not_allowed'/s,
  'audio job proxying must live inside a fail-closed Admin route policy'
);

assert.match(
  abilityModelsPageSource,
  /createAudioPreview[\s\S]*fetch\('\/api\/admin\/audio-jobs'/,
  'ability-model routing dialog must be the visible place that creates audio preview jobs'
);

assert.match(
  abilityModelsPageSource,
  /inspector_tab_preview[\s\S]*audio_preview_title_panel[\s\S]*audio_preview_metadata_only/,
  'ability-model routing dialog must preserve the audio generation workbench with a metadata-only completion state'
);

assert.doesNotMatch(
  abilityModelsPageSource,
  /<audio\b|\/api\/admin\/audio-preview|b64_json/,
  'ability-model routing dialog must not retain audio byte playback or Base64 preview fallbacks'
);

assert.doesNotMatch(
  layoutSource,
  /\/admin\/audio-workbench/,
  'admin navigation must not expose the retired standalone audio workbench'
);

assert.doesNotMatch(
  troubleshootingSource,
  /\/admin\/audio-workbench|action_open_audio_workbench|nav_audio_workbench/,
  'advanced troubleshooting must not expose the retired standalone audio workbench'
);

assert.doesNotMatch(
  i18nSource,
  /nav_audio_workbench|audio_workbench_desc|action_open_audio_workbench/,
  'i18n copy must not keep visible labels for the retired standalone audio workbench'
);

console.log('admin_audio_workbench_contract: ok');
