import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve('.');
const portalRoots = [
  resolve(root, 'src/app/portal'),
  resolve(root, 'src/components/portal'),
];
function collectSourceFiles(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = resolve(directory, entry);
    if (statSync(path).isDirectory()) return collectSourceFiles(path);
    return /\.(?:ts|tsx)$/.test(path) ? [path] : [];
  });
}

for (const file of portalRoots.flatMap(collectSourceFiles)) {
  const source = readFileSync(file, 'utf8');
  assert.doesNotMatch(
    source,
    /@\/components\/backoffice\//,
    `${file} must depend on Portal-owned UI primitives instead of the Admin surface`
  );
}

const scaffoldSource = readFileSync(
  resolve(root, 'src/components/portal/PortalScaffold.tsx'),
  'utf8'
);
for (const component of [
  'PortalPageStack',
  'PortalSection',
  'PortalCard',
  'PortalMetricStrip',
  'PortalPrimaryPanel',
]) {
  assert.match(scaffoldSource, new RegExp(`export function ${component}`));
}
assert.doesNotMatch(scaffoldSource, /Backoffice/, 'Portal primitives must own their implementation');

console.log('portal_surface_boundary_contract: ok');
