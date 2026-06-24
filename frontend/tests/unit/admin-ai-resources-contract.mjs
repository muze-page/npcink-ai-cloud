import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/ai-resources/page.tsx');
const pageSource = readFileSync(pagePath, 'utf8');

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/ai-resources'/,
  'AI resources page must read the shared admin AI resources projection'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/ai-resources\/profile-preferences'/,
  'AI resources page must save only bounded profile preferences through the admin projection'
);

assert.match(
  pageSource,
  /Provider keys stay in Cloud runtime settings/,
  'AI resources page must explain provider settings stay in Cloud runtime'
);

assert.match(
  pageSource,
  /WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page/,
  'AI resources page must not present itself as a second control plane'
);

assert.doesNotMatch(
  pageSource,
  /secret:\s*string/,
  'AI resources page must not model raw provider secrets'
);

assert.doesNotMatch(
  pageSource,
  /api_key|group_id/,
  'AI resources page must not expose provider credential fields'
);

console.log('admin_ai_resources_contract: ok');
