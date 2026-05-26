import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

const root = process.cwd();
const portalAppDir = resolve(root, 'src/app/portal');
const portalComponentsDir = resolve(root, 'src/components/portal');
const workspaceHeaderPath = resolve(root, 'src/components/portal/PortalWorkspaceHeader.tsx');
const siteRecordPath = resolve(root, 'src/app/portal/sites/[siteId]/page.tsx');

function listFiles(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...listFiles(fullPath));
      continue;
    }
    if (/\.(ts|tsx|js|jsx|mjs)$/.test(entry.name)) {
      files.push(fullPath);
    }
  }
  return files;
}

const portalFiles = [...listFiles(portalAppDir), ...listFiles(portalComponentsDir)];
const adminLeaks = [];

for (const filePath of portalFiles) {
  const source = readFileSync(filePath, 'utf8');
  const lines = source.split('\n');
  lines.forEach((line, index) => {
    if (line.includes('admin.')) {
      adminLeaks.push(`${filePath}:${index + 1}: ${line.trim()}`);
    }
  });
}

assert.equal(
  adminLeaks.length,
  0,
  `portal surfaces must not reuse admin.* user-facing semantics:\n${adminLeaks.join('\n')}`
);

const workspaceHeaderSource = readFileSync(workspaceHeaderPath, 'utf8');
assert.match(
  workspaceHeaderSource,
  /'preferences'/,
  'Portal workspace header may identify Preferences as a secondary page'
);
assert.doesNotMatch(
  workspaceHeaderSource,
  /'settings'/,
  'Portal workspace header must not keep the legacy Settings page token'
);

const siteRecordSource = readFileSync(siteRecordPath, 'utf8');
assert.match(
  siteRecordSource,
  /currentPage="record"/,
  '/portal/sites/[siteId] must stay outside the primary portal workspace chain'
);
assert.match(
  siteRecordSource,
  /portal\.read_only_record/,
  '/portal/sites/[siteId] must remain a read-only record surface'
);

for (const route of ['keys', 'usage', 'billing']) {
  assert.match(
    siteRecordSource,
    new RegExp(`/portal/${route}\\?site=\\$\\{siteId\\}`),
    `/portal/sites/[siteId] must link users back into the dedicated ${route} workspace`
  );
}
assert.doesNotMatch(
  siteRecordSource,
  /\/portal\/settings/,
  '/portal/sites/[siteId] must not link users back into the retired Settings surface'
);
assert.doesNotMatch(
  siteRecordSource,
  /\/portal\/preferences/,
  '/portal/sites/[siteId] must not promote Preferences as a site-record workflow'
);

assert.doesNotMatch(
  siteRecordSource,
  /admin\.quick_actions/,
  '/portal/sites/[siteId] must not drift back into an admin-style quick actions dashboard'
);

const siteRecordStats = statSync(siteRecordPath);
assert.ok(siteRecordStats.isFile(), '/portal/sites/[siteId] route must remain implemented as a real page file');
