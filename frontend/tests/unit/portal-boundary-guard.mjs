import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

const root = process.cwd();
const portalAppDir = resolve(root, 'src/app/portal');
const portalComponentsDir = resolve(root, 'src/components/portal');
const workspaceHeaderPath = resolve(root, 'src/components/portal/PortalWorkspaceHeader.tsx');
const sitesPagePath = resolve(root, 'src/components/portal/PortalSitesWorkspace.tsx');

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
assert.doesNotMatch(
  workspaceHeaderSource,
  /'settings'/,
  'Portal workspace header must not keep the legacy Settings page token'
);
assert.doesNotMatch(
  workspaceHeaderSource,
  /'preferences'/,
  'Portal workspace header must not keep the retired Preferences page token'
);

const sitesPageSource = readFileSync(sitesPagePath, 'utf8');
assert.doesNotMatch(
  sitesPageSource,
  /\/portal\/settings/,
  'the merged site workspace must not link users back into the retired Settings surface'
);
assert.doesNotMatch(
  sitesPageSource,
  /\/portal\/preferences/,
  'the merged site workspace must not promote Preferences as a site workflow'
);
assert.doesNotMatch(
  sitesPageSource,
  /admin\.quick_actions/,
  'the merged site workspace must not drift back into an admin-style quick actions dashboard'
);

const sitesPageStats = statSync(sitesPagePath);
assert.ok(sitesPageStats.isFile(), 'the merged site workspace must remain implemented as a real component file');
