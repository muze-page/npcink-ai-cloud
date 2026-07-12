import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fromFrontendRoot } from './_paths.mjs';

const adminRoot = fromFrontendRoot('src/app/admin');
const architectureSource = readFileSync(
  fromFrontendRoot('../docs/cloud-admin-information-architecture-v2.md'),
  'utf8'
);
const decisionSource = readFileSync(
  fromFrontendRoot('../docs/decisions/002-cloud-admin-task-oriented-information-architecture.md'),
  'utf8'
);
const feedbackContractSource = readFileSync(
  fromFrontendRoot('../docs/cloud-admin-feedback-and-layout-contract-v1.md'),
  'utf8'
);

function listPageFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return listPageFiles(path);
    }
    return entry.isFile() && entry.name === 'page.tsx' ? [path] : [];
  });
}

function routeForPage(path) {
  const routePart = relative(adminRoot, path)
    .split(sep)
    .slice(0, -1)
    .join('/');
  return routePart ? `/admin/${routePart}` : '/admin';
}

const actualRoutes = listPageFiles(adminRoot).map(routeForPage).sort();
assert.equal(actualRoutes.length, 24, 'admin route inventory must be reviewed when its size changes');

for (const route of actualRoutes) {
  assert.ok(
    architectureSource.includes(`| \`${route}\` |`),
    `${route} must be classified in the admin IA route matrix`
  );
}

for (const pageModel of ['overview', 'queue', 'detail', 'configuration', 'diagnostic', 'authentication']) {
  assert.ok(
    architectureSource.includes(`\`${pageModel}\``),
    `${pageModel} page model must remain explicitly defined`
  );
}

for (const state of ['loading', 'empty', 'filtered_empty', 'error', 'success', 'disabled', 'pending']) {
  assert.ok(
    architectureSource.includes(`| \`${state}\` |`),
    `${state} must remain part of the shared admin state model`
  );
}

for (const riskClass of ['routine', 'governed', 'destructive']) {
  assert.ok(
    architectureSource.includes(`\`${riskClass}\``),
    `${riskClass} action risk class must remain defined`
  );
}

assert.match(
  architectureSource,
  /Customer detail:[\s\S]*Service queue:[\s\S]*Service settings:/,
  'the three representative page-model pilots must remain explicit'
);
assert.match(
  architectureSource,
  /must not become:[\s\S]*second WordPress control plane[\s\S]*WordPress approval/,
  'the IA contract must preserve the Cloud and WordPress ownership boundary'
);
assert.match(
  architectureSource,
  /cloud-admin-feedback-and-layout-contract-v1\.md/,
  'the IA contract must compose with the existing feedback and receipt contract'
);
assert.match(
  feedbackContractSource,
  /## 4\. Feedback Taxonomy[\s\S]*### 4\.5 Auditable mutation receipt/,
  'the referenced feedback contract must continue to define receipt handling'
);
assert.match(decisionSource, /## Status\s+Accepted\./, 'the task-oriented admin IA decision must be accepted');
assert.match(
  decisionSource,
  /presentation consolidation does\s+not merge APIs or data truth/,
  'the ADR must prevent UI consolidation from moving data ownership'
);

console.log(`admin_information_architecture_v2_contract: ok (${actualRoutes.length} routes)`);
