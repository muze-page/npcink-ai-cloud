import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fromFrontendRoot } from './_paths.mjs';

const adminRoot = fromFrontendRoot('src/app/admin');
const inspectedFiles = [];

function collectClientSurfaces(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      collectClientSurfaces(path);
      continue;
    }
    if (entry.name === 'page.tsx' || entry.name === 'layout.tsx') {
      inspectedFiles.push(path);
    }
  }
}

collectClientSurfaces(adminRoot);
inspectedFiles.push(
  fromFrontendRoot('src/components/admin/AdminAuditSummaryPanel.tsx')
);

assert.ok(inspectedFiles.length > 20, 'Admin client-surface inventory must remain comprehensive');

for (const path of inspectedFiles) {
  const source = readFileSync(path, 'utf8');
  assert.doesNotMatch(
    source,
    /\bfetch\s*\(/,
    `${relative(adminRoot, path)} must use the shared strict ApiClient instead of raw fetch`
  );
}

const advisorSource = readFileSync(
  fromFrontendRoot('src/app/admin/ai-advisor/page.tsx'),
  'utf8'
);
assert.match(
  advisorSource,
  /<AdvisorEvaluationDetails onToggle=\{setEvaluationDetailsOpen\}>/,
  'Advisor must keep secondary evaluation reads behind the explicit details disclosure'
);
assert.match(
  advisorSource,
  /Promise\.allSettled\(\[[\s\S]*loadHistory\(\)[\s\S]*loadValueMetrics/,
  'Advisor must load history and value evidence only through the bounded details loader'
);

console.log('admin_shared_api_client_contract: ok');
