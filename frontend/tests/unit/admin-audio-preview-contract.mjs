import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/audio-preview/route.ts');
const abilityModelsPagePath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');

const routeSource = readFileSync(routePath, 'utf8');
const abilityModelsPageSource = readFileSync(abilityModelsPagePath, 'utf8');

assert.match(
  routeSource,
  /const sessionResult = await requireAdminSessionData\(request\);[\s\S]*?if \(sessionResult instanceof NextResponse\)/,
  'audio preview proxy must validate the admin session before fetching external audio'
);

assert.match(
  routeSource,
  /url\.protocol === 'https:' && ALLOWED_MINIMAX_AUDIO_HOSTS\.has\(url\.hostname\)/,
  'audio preview proxy must allowlist HTTPS MiniMax audio hosts'
);

assert.match(
  routeSource,
  /isAllowedCloudArtifactUrl[\s\S]*\/v1\\\/runtime\\\/artifacts\\\/art_\[A-Za-z0-9\]\+\\\/public-download/,
  'audio preview proxy must allowlist Cloud runtime audio artifact URLs'
);

assert.match(
  routeSource,
  /buildBackendUrl\(`\$\{parsed\.url\.pathname\}\$\{parsed\.url\.search\}`\)/,
  'audio preview proxy must fetch Cloud artifact URLs through the backend API base'
);

assert.match(
  routeSource,
  /headers\.Range = range;/,
  'audio preview proxy must forward browser Range requests'
);

assert.match(
  routeSource,
  /headers\.Range = 'bytes=0-0';/,
  'audio preview proxy must avoid upstream HEAD requests against signed MiniMax URLs'
);

assert.match(
  abilityModelsPageSource,
  /\/api\/admin\/audio-preview\?url=\$\{encodeURIComponent\(audio\.url\)\}/,
  'ability-model audio preview playback must use the same-origin audio preview proxy'
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
