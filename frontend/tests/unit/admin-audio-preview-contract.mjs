import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const runtimeProfilesPagePath = resolve(process.cwd(), 'src/app/admin/runtime-profiles/page.tsx');
const legacyByteProxyPath = resolve(process.cwd(), 'src/app/api/admin/audio-preview/route.ts');
const adminProxyPath = resolve(process.cwd(), 'src/app/api/admin/[...path]/route.ts');
const runtimeProfilesSource = readFileSync(runtimeProfilesPagePath, 'utf8');
const adminProxySource = readFileSync(adminProxyPath, 'utf8');

assert.equal(existsSync(legacyByteProxyPath), false, 'the legacy audio preview byte proxy must remain removed');
assert.doesNotMatch(adminProxySource, /audio-jobs/, 'the browser admin proxy must not retain internal audio preview job routes');

for (const forbiddenPattern of [
  /\/api\/admin\/audio-jobs/,
  /\/api\/admin\/audio-preview/,
  /audioPreview|AudioPreview|audio_preview/,
  /public-download/,
  /ALLOWED_MINIMAX_AUDIO_HOSTS/,
  /b64_json/,
  /data:audio\//,
  /<audio\b/,
  /<textarea\b/,
]) {
  assert.doesNotMatch(
    runtimeProfilesSource,
    forbiddenPattern,
    `hosted runtime profiles must not contain the retired audio preview UI: ${forbiddenPattern}`
  );
}

console.log('admin_audio_preview_contract: ok');
