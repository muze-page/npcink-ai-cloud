import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const pagePath = resolve(root, 'src/app/admin/agent-feedback/page.tsx');
const source = readFileSync(pagePath, 'utf8');

assert.match(
  source,
  /createApiClient[\s\S]*\.request<unknown>\(`\/api\/admin\/agent-feedback\?\$\{params\.toString\(\)\}`/,
  'agent feedback admin page must load the read-only admin summary endpoint'
);
assert.match(
  source,
  /status="read_only"/,
  'agent feedback admin page must identify itself as read-only'
);
assert.match(
  source,
  /WordPress approval, preflight, and final writes stay local/,
  'agent feedback admin page must preserve the local WordPress truth boundary in copy'
);

const blockedMutationFragments = [
  /method:\s*['"`](POST|PUT|PATCH|DELETE)['"`]/,
  /\/api\/admin\/agent-feedback[^'"`]*\/(?:save|apply|publish|execute|approve)/,
  /\b(save|apply|publish|execute|approve|write_confirmed|confirm_token)\b/i,
];

const allowedReadOnlyFragments = [
  'final writes stay local',
  'Final write',
  'No mutation',
  'productionMutation',
  'production_mutation',
  'Mutation enabled',
];

let scanSource = source;
for (const fragment of allowedReadOnlyFragments) {
  scanSource = scanSource.replaceAll(fragment, '');
}

for (const pattern of blockedMutationFragments) {
  assert.doesNotMatch(
    scanSource,
    pattern,
    `agent feedback admin page must not expose mutation controls matching ${pattern}`
  );
}

console.log('admin_agent_feedback_boundary_contract: ok');
