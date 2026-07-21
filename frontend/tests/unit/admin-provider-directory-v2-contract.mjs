import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const pageSource = readFileSync(resolve(root, 'src/app/admin/ai-resources/page.tsx'), 'utf8');
const directorySource = readFileSync(resolve(root, 'src/components/admin/SupplierConnectionTables.tsx'), 'utf8');
const summarySource = readFileSync(resolve(root, 'src/components/admin/SupplierSummaryCards.tsx'), 'utf8');
const toolbarSource = readFileSync(resolve(root, 'src/components/admin/SupplierToolbar.tsx'), 'utf8');

assert.match(
  summarySource,
  /data-ui="supplier-summary-strip"[\s\S]*grid-cols-2[\s\S]*divide-x/,
  'Provider readiness must use one compact summary strip at every viewport'
);

assert.doesNotMatch(
  directorySource,
  /<table|min-w-\[(?:760|960)px\]/,
  'Provider queues must not force fixed-width tables or horizontal scrolling on narrow screens'
);

assert.match(
  directorySource,
  /data-ui="model-supplier-directory"[\s\S]*aria-pressed=\{isSelected\}[\s\S]*data-ui="supplier-inspector"/,
  'Model suppliers must render as a selectable queue with a contextual inspector'
);

assert.doesNotMatch(
  directorySource,
  /capability-supplier-directory|CapabilitySupplierTable|capability_category_filter/,
  'The model supplier directory must not retain the retired capability supplier queue'
);

assert.match(
  pageSource,
  /usePathname[\s\S]*useRouter[\s\S]*selectedConnectionId = searchParams\.get\('focus'\)[\s\S]*updateWorkspaceParams/,
  'Provider workspace focus must be URL-backed'
);

for (const key of ['q', 'status', 'focus']) {
  assert.match(pageSource, new RegExp(`${key}:`), `Provider workspace must persist ${key} state in the URL`);
}

assert.match(
  pageSource,
  /resourcesRequestActiveRef[\s\S]*resourcesRequestSequenceRef[\s\S]*resourcesLoadedRef[\s\S]*if \(resourcesRequestActiveRef\.current\) return/,
  'Provider catalog reads must deduplicate development Strict Mode requests and reject stale replacement'
);

assert.match(
  toolbarSource,
  /field_search_connections[\s\S]*action_add_model_supplier/,
  'The toolbar must expose model supplier search and its bounded add action'
);

assert.doesNotMatch(
  toolbarSource,
  /supplierTypeFilter|action_add_capability_supplier/,
  'The model supplier toolbar must not duplicate capability-service controls'
);

assert.match(
  directorySource,
  /inspector_boundary[\s\S]*Cloud runtime provider detail[\s\S]*Model routing and WordPress control/,
  'Provider inspectors must state their Cloud runtime read boundary'
);

console.log('admin_provider_directory_v2_contract: ok');
