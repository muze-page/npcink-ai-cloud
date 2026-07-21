import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const scaffold = readFileSync(resolve(process.cwd(), 'src/components/backoffice/BackofficeScaffold.tsx'), 'utf8');
const pages = [
  'src/app/admin/media-observability/page.tsx',
  'src/app/admin/vector-observability/page.tsx',
  'src/app/admin/agent-feedback/page.tsx',
].map((path) => ({ path, source: readFileSync(resolve(process.cwd(), path), 'utf8') }));

assert.match(scaffold, /export function BackofficeDiagnosticNotice\(/, 'shared diagnostic notice must be exported');
assert.match(scaffold, /role="alert"/, 'shared diagnostic notice must expose an alert role');
assert.match(scaffold, /export function BackofficeDisclosure\(/, 'shared advanced evidence disclosure must be exported');
assert.match(scaffold, /<details/, 'shared advanced evidence disclosure must use native details semantics');

for (const { path, source } of pages) {
  assert.match(source, /BackofficeDiagnosticNotice/, `${path} must use the shared diagnostic notice`);
  assert.match(source, /BackofficeDisclosure/, `${path} must use the shared evidence disclosure`);
  assert.doesNotMatch(source, /role="alert"/, `${path} must not duplicate the diagnostic alert shell`);
  assert.doesNotMatch(source, /<details className="rounded-\[1\.35rem\]/, `${path} must not duplicate the advanced disclosure shell`);
}
