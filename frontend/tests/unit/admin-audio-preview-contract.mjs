import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/audio-preview/route.ts');
const abilityModelsPagePath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');

const abilityModelsPageSource = readFileSync(abilityModelsPagePath, 'utf8');

assert.equal(existsSync(routePath), false, 'the legacy audio preview byte proxy must be removed');

for (const forbiddenPattern of [
  /\/api\/admin\/audio-preview/,
  /public-download/,
  /ALLOWED_MINIMAX_AUDIO_HOSTS/,
  /b64_json/,
  /data:audio\//,
  /<audio\b/,
]) {
  assert.doesNotMatch(
    abilityModelsPageSource,
    forbiddenPattern,
    `ability-model audio generation surface must not contain ${forbiddenPattern}`
  );
}

assert.match(
  abilityModelsPageSource,
  /audio_preview_metadata_only[\s\S]*activeAudioPreviewArtifactId[\s\S]*audio_preview_artifact/,
  'ability-model audio generation surface must show a metadata-only completion state and artifact evidence'
);

assert.match(
  abilityModelsPageSource,
  /preview_instance_id: previewInstanceId/,
  'ability-model audio preview must pass the selected route candidate without saving the route'
);

assert.match(
  abilityModelsPageSource,
  /const \[audioPreviewText, setAudioPreviewText\][\s\S]*body: previewText/,
  'ability-model audio preview must send the operator-entered preview text instead of a fixed sample body'
);

assert.doesNotMatch(
  abilityModelsPageSource,
  /site_id:\s*['"]site_smoke['"]/,
  'ability-model audio preview must not hard-code the archived smoke-test site'
);

assert.match(
  abilityModelsPageSource,
  /audio_preview_text_label[\s\S]*<textarea[\s\S]*maxLength=\{500\}/,
  'ability-model audio preview must expose an editable bounded preview text field'
);

assert.match(
  abilityModelsPageSource,
  /normalizeAudioPreviewError[\s\S]*errorCode[\s\S]*siteId[\s\S]*runtimeErrorCode[\s\S]*traceId[\s\S]*activeAudioPreviewEvidence/,
  'ability-model audio preview must preserve backend error evidence for troubleshooting'
);

console.log('admin_audio_preview_contract: ok');
