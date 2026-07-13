import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const page = readFileSync(fromFrontendRoot('src/app/admin/vector-settings/page.tsx'), 'utf8');
const layout = readFileSync(fromFrontendRoot('src/app/admin/layout.tsx'), 'utf8');

assert.match(page, /data-page-model="configuration"/, 'Vector settings must use the configuration page model');
assert.match(page, /Embedding model[\s\S]*Vector database[\s\S]*Result reranking/, 'Vector settings must separate embedding, storage, and reranking');
assert.match(page, /embedding_provider[\s\S]*vector_store_provider[\s\S]*rerank_provider/, 'Vector settings must use fixed mutually exclusive runtime slots');
assert.match(page, /data-vector-group=\{group\.id\}/, 'Each vector configuration group must expose a stable interaction boundary');
assert.match(page, /store_postgres[\s\S]*store_zilliz/, 'Vector storage must expose built-in PostgreSQL and Zilliz as fixed choices');
assert.match(page, /model_id[\s\S]*dimensions[\s\S]*collection[\s\S]*top_k/, 'Vector settings must preserve compatibility-critical model and storage fields');
assert.match(page, /rebuild existing indexes|现有索引可能需要重建/, 'Vector settings must warn about index rebuilds after compatibility changes');
assert.match(page, /\/admin\/vector-observability/, 'Vector settings must link to the existing read-only diagnostics surface');
assert.doesNotMatch(page, /priority|channel note|通道备注/, 'Vector settings must not reintroduce channel priority or notes');
assert.match(layout, /href: '\/admin\/vector-settings'[\s\S]*activePrefixes: \['\/admin\/vector-settings'\]/, 'Admin navigation must expose Vector Settings under Runtime Plane');

console.log('admin_vector_settings_contract: ok');
