import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const source = readFileSync(resolve(frontendRoot, 'src/app/admin/credit-packs/page.tsx'), 'utf8');
const defaultSurfaceStart = source.indexOf('<BackofficePageStack className="space-y-5">');
const editorStart = source.indexOf('<Modal', defaultSurfaceStart);
const defaultSurface = source.slice(defaultSurfaceStart, editorStart);
const editorSurface = source.slice(editorStart);

assert.match(source, /usePathname[\s\S]*useRouter[\s\S]*searchParams\.get\('status'\)[\s\S]*searchParams\.get\('focus'\)/, 'Credit pack filter and focus must be URL-backed');
assert.match(source, /requestActiveRef[\s\S]*requestSequenceRef[\s\S]*hasLoadedRef[\s\S]*if \(requestActiveRef\.current\) return/, 'Credit pack reads must deduplicate Strict Mode requests and reject stale replacement');
assert.match(defaultSurface, /BackofficeLayer[\s\S]*BackofficeSummaryStrip[\s\S]*data-ui="credit-pack-directory-item"[\s\S]*id="credit-pack-inspector"/, 'The default surface must use compact orientation, directory, and inspector layers');
assert.doesNotMatch(defaultSurface, /<input|<textarea/, 'The default credit pack directory must be read-only until one pack enters edit mode');
assert.doesNotMatch(defaultSurface, /common\.save|handleSaveDraft/, 'The default header and directory must not expose an ambiguous save-all action');
assert.match(editorSurface, /isOpen=\{Boolean\(draft\)\}[\s\S]*isDraftDirty[\s\S]*handleSaveDraft/, 'The editor must save only an explicitly changed selected pack');
assert.match(source, /items\.map\(\(item\) => item\.pack_id === draft\.pack_id \? normalizeItem\(draft\) : normalizeItem\(item\)\)[\s\S]*saveCatalog\(nextItems\)/, 'One-pack editing must preserve the atomic complete-catalog PATCH contract');
assert.match(source, /useToast\(\)[\s\S]*toast\.success/, 'Successful pack updates must use non-shifting global Toast feedback');
assert.match(source, /credit_packs_inspector_boundary[\s\S]*purchase-time snapshot[\s\S]*package entitlement and WordPress control/, 'The inspector must explain purchase snapshot and ownership boundaries');
assert.doesNotMatch(source, /BackofficePrimaryPanel|BackofficeMetricStrip|BackofficeStackCard/, 'The credit pack configuration page must not regress to a hero metric panel or editable card wall');

console.log('admin_credit_packs_directory_v2_contract: ok');
