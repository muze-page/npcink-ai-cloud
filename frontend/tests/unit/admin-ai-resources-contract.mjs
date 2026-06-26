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
  /fetch\('\/api\/admin\/provider-connections'/,
  'AI resources page must save provider connections through the bounded admin endpoint'
);

assert.match(
  pageSource,
  /provider-connections\/.*\/test/,
  'AI resources page must test managed provider connections through the bounded admin endpoint'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/provider-connections\/import-env'/,
  'AI resources page must import environment providers through a bounded admin endpoint'
);

assert.match(
  pageSource,
  /Provider connections can be managed in Cloud runtime storage/,
  'AI resources page must explain provider connections are managed by Cloud runtime storage'
);

assert.match(
  pageSource,
  /WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page/,
  'AI resources page must not present itself as a second control plane'
);

assert.match(
  pageSource,
  /Recent runtime evidence/,
  'AI resources page must expose recent runtime evidence for operator debugging'
);

assert.match(
  pageSource,
  /Capability Matrix/,
  'AI resources page must expose the capability-to-provider-model matrix'
);

assert.match(
  pageSource,
  /Runtime resolution/,
  'AI resources page must expose the current runtime resolution'
);

assert.match(
  pageSource,
  /Feature usage/,
  'AI resources page must expose feature-to-model usage'
);

assert.match(
  pageSource,
  /Model health/,
  'AI resources page must expose provider-model health diagnostics'
);

assert.match(
  pageSource,
  /Feature-to-model evidence from Cloud runtime metadata/,
  'Feature usage must be framed as runtime metadata evidence'
);

assert.match(
  pageSource,
  /does not change routing, prompts, abilities, or WordPress writes/,
  'Feature usage must remain read-only and outside control-plane truth'
);

assert.match(
  pageSource,
  /Provider\/model health from provider_call_records/,
  'Model health must be backed by provider call metadata'
);

assert.match(
  pageSource,
  /Metadata only: prompts, results, and provider secrets are not exposed/,
  'Model health must not expose prompt, result, or secret material'
);

assert.match(
  pageSource,
  /read-only diagnostics and does not change routing, prompts, abilities, or WordPress writes/,
  'Model health must remain diagnostics-only'
);

assert.match(
  pageSource,
  /read-only operator evidence, not a router editor/,
  'AI resources runtime resolution must not present itself as a router editor'
);

assert.match(
  pageSource,
  /Environment migration/,
  'AI resources page must expose environment-to-DB migration status'
);

assert.match(
  pageSource,
  /Environment values remain fallback only/,
  'AI resources page must explain env values are fallback only'
);

assert.match(
  pageSource,
  /Cloud runtime mapping from capability to profile, provider, model, and write posture/,
  'AI resources matrix must explain the runtime mapping purpose'
);

assert.match(
  pageSource,
  /not a WordPress ability editor/,
  'AI resources matrix must not present itself as a local ability editor'
);

assert.match(
  pageSource,
  /Enabled:/,
  'AI resources connections view must expose provider enabled state'
);

assert.match(
  pageSource,
  /Configured:/,
  'AI resources connections view must expose masked provider configured state'
);

assert.match(
  pageSource,
  /Last test:/,
  'AI resources connections view must expose masked provider test diagnostics'
);

assert.match(
  pageSource,
  /Prompt and result content are not exposed here/,
  'AI resources runtime evidence must be metadata-only'
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
