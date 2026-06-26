import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const routePath = resolve(process.cwd(), 'src/app/api/admin/audio-preview/route.ts');
const workbenchPagePath = resolve(process.cwd(), 'src/app/admin/audio-workbench/page.tsx');

const routeSource = readFileSync(routePath, 'utf8');
const workbenchPageSource = readFileSync(workbenchPagePath, 'utf8');

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
  /headers\.Range = range;/,
  'audio preview proxy must forward browser Range requests'
);

assert.match(
  routeSource,
  /headers\.Range = 'bytes=0-0';/,
  'audio preview proxy must avoid upstream HEAD requests against signed MiniMax URLs'
);

assert.match(
  workbenchPageSource,
  /\/api\/admin\/audio-preview\?url=\$\{encodeURIComponent\(audio\.url\)\}/,
  'audio workbench playback must use the same-origin audio preview proxy'
);

console.log('admin_audio_preview_contract: ok');
