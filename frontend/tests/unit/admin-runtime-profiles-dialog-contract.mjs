import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

import { fromFrontendRoot } from './_paths.mjs';

const pageSource = readFileSync(
  fromFrontendRoot('src/app/admin/runtime-profiles/page.tsx'),
  'utf8'
);

assert.match(
  pageSource,
  /createApiClient\(\{ idempotencyPrefix: 'runtime_profiles' \}\)[\s\S]*\.request<RuntimeProfilesData>\('\/api\/admin\/runtime-profiles'\)/,
  'hosted runtime profiles must load through the shared ApiClient'
);

assert.match(
  pageSource,
  /\.request<RuntimeProfilesData>\('\/api\/admin\/runtime-profiles', \{[\s\S]*method: 'PUT'[\s\S]*body: \{[\s\S]*contract_version: 'cloud-hosted-runtime-profiles\.v1'[\s\S]*platform_kind: 'wordpress'[\s\S]*connector_id: 'wordpress_ai_connector'[\s\S]*operation_contract_version: 'wordpress_operation\.v1'[\s\S]*profiles:/,
  'hosted runtime profile saves must use PUT with all four contract identity fields'
);

const supersededConnectorContractField = ['connector', 'contract', 'version'].join('_');
const supersededConnectorContractMarker = ['wp_ai_connector', 'runtime.v1'].join('_');
assert.equal(
  pageSource.includes(supersededConnectorContractField),
  false,
  'hosted runtime profiles must not retain the superseded connector contract field'
);
assert.equal(
  pageSource.includes(supersededConnectorContractMarker),
  false,
  'hosted runtime profiles must not retain the superseded connector contract marker'
);
assert.match(
  pageSource,
  /const SUPERSEDED_CONNECTOR_CONTRACT_FIELD = \['connector', 'contract', 'version'\]\.join\('_'\);[\s\S]*if \(SUPERSEDED_CONNECTOR_CONTRACT_FIELD in data\)[\s\S]*throw new TypeError\('Hosted runtime profile contract contains superseded connector contract identity\.'/,
  'hosted runtime profile responses must reject the superseded field instead of accepting a dual contract identity'
);

assert.doesNotMatch(pageSource, /\bfetch\s*\(/, 'hosted runtime profiles must not use raw fetch');

for (const contractLiteral of [
  'cloud-hosted-runtime-profiles.v1',
  'admin_hosted_runtime_profiles',
  'hosted_runtime_profile_configuration',
  'cloud_runtime',
  'wordpress',
  'wordpress_ai_connector',
  'wordpress_operation.v1',
]) {
  assert.ok(pageSource.includes(contractLiteral), `hosted runtime profile page must retain ${contractLiteral}`);
}

assert.match(
  pageSource,
  /available_instances: \{[\s\S]*text: RuntimeInstance\[\][\s\S]*vision: RuntimeInstance\[\][\s\S]*image_generation: RuntimeInstance\[\][\s\S]*audio_generation: RuntimeInstance\[\]/,
  'hosted runtime profiles must consume the bounded cross-media instance projection'
);

assert.match(
  pageSource,
  /const expectedIdentity: Record<string, string> = \{[\s\S]*contract_version: 'cloud-hosted-runtime-profiles\.v1'[\s\S]*surface: 'admin_hosted_runtime_profiles'[\s\S]*projection_kind: 'hosted_runtime_profile_configuration'[\s\S]*owner: 'cloud_runtime'[\s\S]*platform_kind: 'wordpress'[\s\S]*connector_id: 'wordpress_ai_connector'[\s\S]*operation_contract_version: 'wordpress_operation\.v1'[\s\S]*for \(const \[field, expected\] of Object\.entries\(expectedIdentity\)\)[\s\S]*if \(data\[field\] !== expected\)[\s\S]*throw new TypeError\(`Hosted runtime profile contract identity mismatch:/,
  'all seven response identity fields must fail closed on mismatch'
);

assert.match(
  pageSource,
  /operation_contract_version[\s\S]*Operation contract/,
  'hosted runtime profile contract details must label the operation contract identity'
);

assert.match(
  pageSource,
  /if \(!data\.available_instances \|\| typeof data\.available_instances !== 'object' \|\| Array\.isArray\(data\.available_instances\)\)[\s\S]*throw new TypeError\('Hosted runtime profile contract requires available_instances object\.'/,
  'available_instances must be a required object instead of silently becoming empty'
);

assert.match(
  pageSource,
  /const requiredInstanceKinds = \['text', 'vision', 'image_generation', 'audio_generation'\] as const;[\s\S]*for \(const kind of requiredInstanceKinds\)[\s\S]*if \(!Array\.isArray\(available\[kind\]\)\)[\s\S]*throw new TypeError\(`Hosted runtime profile contract requires available_instances\.\$\{kind\} array\./,
  'all four available instance kinds must be required arrays'
);

assert.match(
  pageSource,
  /if \(!Array\.isArray\(data\.profiles\)\)[\s\S]*throw new TypeError\('Hosted runtime profile contract requires profiles array\.'/,
  'profiles must be a required array instead of silently becoming empty'
);

assert.match(
  pageSource,
  /function normalizeRuntimeProfile[\s\S]*throw new TypeError\('Hosted runtime profile must be an object\.'/,
  'malformed profile items must fail closed'
);

for (const requiredProfileGuard of [
  /item\.platform_kind !== 'wordpress' \|\| item\.connector_id !== 'wordpress_ai_connector'[\s\S]*throw new TypeError\('Hosted runtime profile identity does not match/,
  /if \(!profileId\)[\s\S]*throw new TypeError\('Hosted runtime profile requires a non-empty profile_id\.'/,
  /!Array\.isArray\(item\.tasks\) \|\| !Array\.isArray\(item\.candidate_instance_ids\)[\s\S]*throw new TypeError\(`Hosted runtime profile \$\{profileId\} requires tasks and candidate_instance_ids arrays\./,
  /item\.tasks\.some[\s\S]*requires non-empty string task identifiers/,
  /item\.candidate_instance_ids\.some[\s\S]*requires non-empty string candidate instance identifiers/,
  /item\.candidate_instance_ids\.length > 2[\s\S]*supports at most two candidate instance identifiers/,
  /!SUPPORTED_EXECUTION_KINDS\.has\(executionKind\)[\s\S]*unsupported execution_kind/,
  /if \(profileIds\.has\(profile\.profile_id\)\)[\s\S]*throw new TypeError\(`Hosted runtime profile_id is duplicated:/,
]) {
  assert.match(pageSource, requiredProfileGuard, `profile validation must retain ${requiredProfileGuard}`);
}

assert.match(
  pageSource,
  /function clearCandidate[\s\S]*position === 0[\s\S]*\? \[\][\s\S]*candidate_instance_ids\.slice\(0, 1\)/,
  'candidate editing must support an explicit empty chain and independent fallback removal'
);

assert.match(
  pageSource,
  /disabled=\{primary \|\| !editingProfile\.candidate_instance_ids\[0\]\}/,
  'a fallback cannot be selected before the primary candidate exists'
);

assert.match(
  pageSource,
  /function normalizeRuntimeInstance[\s\S]*throw new TypeError\('Hosted runtime instance must be an object\.'[\s\S]*if \(!instanceId \|\| !providerId \|\| !modelId\)[\s\S]*throw new TypeError\('Hosted runtime instance requires instance_id, provider_id, and model_id\.'/,
  'runtime instances must reject malformed items and missing routing identity'
);

for (const silentFallback of [
  /const item = value && typeof value === 'object' \? value as Record<string, unknown> : \{\}/,
  /const available = data\.available_instances[\s\S]*: \{\}/,
  /const list = \(key: string\) => Array\.isArray\(available\[key\]\)[\s\S]*: \[\]/,
  /profiles: Array\.isArray\(data\.profiles\)[\s\S]*: \[\]/,
  /\.filter\(\(item\) => item\.instance_id\)|\.filter\(\(profile\) => profile\.profile_id\)/,
]) {
  assert.doesNotMatch(pageSource, silentFallback, `contract validation must not silently coerce invalid data with ${silentFallback}`);
}

assert.match(
  pageSource,
  /function instanceLabel[\s\S]*provider_display_name \|\| instance\.provider_id[\s\S]*instance\.model_id[\s\S]*Primary model[\s\S]*instanceLabel\(instancesById\.get/,
  'selected candidate summaries must preserve the supplier and model route label'
);

assert.match(
  pageSource,
  /function profileTone[\s\S]*modelStatus !== 'available' \|\| healthStatus === 'unhealthy'[\s\S]*return 'error'[\s\S]*healthStatus !== 'healthy'[\s\S]*return 'warning'[\s\S]*return 'success'/,
  'profile readiness must require an available and healthy primary model, block unhealthy, and warn on unknown health'
);

const dialogIndex = pageSource.indexOf('createPortal(');
const candidateRowsIndex = pageSource.indexOf('candidates.map');
assert.ok(dialogIndex >= 0, 'hosted runtime profile editing must use a bounded dialog');
assert.ok(candidateRowsIndex > dialogIndex, 'model candidates must only render inside the edit dialog');
assert.equal(pageSource.indexOf('candidates.map', candidateRowsIndex + 1), -1, 'model candidates must not be duplicated outside the dialog');

assert.match(
  pageSource,
  /const dialogRef = useDialogKeyboard<[\s\S]*ref=\{dialogRef\}/,
  'the runtime profile dialog must keep Escape, focus containment, and trigger restoration'
);

assert.match(
  pageSource,
  /setReceipt\(next\.receipt \|\| null\)[\s\S]*<AdminMutationReceipt receipt=\{receipt\}/,
  'successful saves must surface the backend mutation receipt'
);

assert.match(
  pageSource,
  /useEffect\(\(\) => \{[\s\S]*if \(!dirty\) return;[\s\S]*const handleBeforeUnload = \(event: BeforeUnloadEvent\)[\s\S]*event\.preventDefault\(\)[\s\S]*event\.returnValue = ''[\s\S]*window\.addEventListener\('beforeunload', handleBeforeUnload\)[\s\S]*window\.removeEventListener\('beforeunload', handleBeforeUnload\)[\s\S]*\}, \[dirty\]\)/,
  'dirty hosted runtime profile drafts must guard browser unload and clean up the handler'
);

assert.match(
  pageSource,
  /const handleAnchorClick = \(event: MouseEvent\)[\s\S]*event\.target instanceof Element \? event\.target\.closest\('a\[href\]'\)[\s\S]*destination\.origin !== window\.location\.origin \|\| destination\.pathname === window\.location\.pathname[\s\S]*event\.preventDefault\(\)[\s\S]*setPendingNavigationHref\([\s\S]*document\.addEventListener\('click', handleAnchorClick, true\)[\s\S]*document\.removeEventListener\('click', handleAnchorClick, true\)/,
  'dirty drafts must capture same-origin anchor navigation before Next.js discards the draft'
);

assert.match(
  pageSource,
  /<ConfirmModal[\s\S]*isOpen=\{Boolean\(pendingNavigationHref\)\}[\s\S]*unsaved_leave_title[\s\S]*unsaved_leave_desc[\s\S]*discard_and_leave[\s\S]*onClose=\{\(\) => setPendingNavigationHref\(''\)\}[\s\S]*setDrafts\(data\.profiles\)[\s\S]*setBaseline\(profileSnapshot\(data\.profiles\)\)[\s\S]*router\.push\(href\)/,
  'dirty navigation must use the shared ConfirmModal and only discard the draft on confirmation'
);

assert.doesNotMatch(pageSource, /window\.confirm/, 'dirty navigation must not use a browser-native confirmation dialog');

assert.doesNotMatch(
  pageSource,
  /ability-models|runtime-binding|runtime-projection|plugin-routing|embedding|audio-jobs|audio preview/i,
  'the new page must not retain the retired ability-model, embedding binding, or audio preview surfaces'
);

console.log('admin_runtime_profiles_dialog_contract: ok');
