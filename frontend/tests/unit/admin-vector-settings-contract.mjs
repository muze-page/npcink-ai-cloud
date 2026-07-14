import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const page = readFileSync(fromFrontendRoot('src/app/admin/vector-settings/page.tsx'), 'utf8');
const layout = readFileSync(fromFrontendRoot('src/app/admin/layout.tsx'), 'utf8');

assert.match(page, /data-page-model="configuration"/, 'Vector settings must use the configuration page model');
assert.match(page, /data-vector-section="fixed-profile"[\s\S]*data-vector-section="provider-key"[\s\S]*data-vector-section="vector-store"/, 'Vector settings must present the fixed profile before its two credential sections');
assert.match(page, /admin\.vector_settings\.model[\s\S]*BAAI\/bge-m3/, 'Vector settings must render the localized fixed model fact');
assert.match(page, /admin\.vector_settings\.dimensions[\s\S]*1024[\s\S]*admin\.vector_settings\.metric[\s\S]*COSINE/, 'Vector settings must preserve the fixed dimensions and metric');
assert.match(page, /Zilliz Endpoint[\s\S]*Zilliz Token[\s\S]*site_knowledge_zh_v1/, 'Vector storage must expose only credentials beside the fixed collection');
assert.match(page, /site-knowledge-vector-profile\/vector-store/, 'Vector storage must save through the dedicated verified profile endpoint');
assert.match(page, /data-vector-section="validation"[\s\S]*连接检测[\s\S]*索引检测[\s\S]*真实检索/, 'Vector settings must distinguish connection, index, and live retrieval evidence');
assert.match(page, /site-knowledge-vector-profile\/index-rebuilds[\s\S]*rebuild_site_knowledge_index/, 'Vector settings must rebuild through the fixed server-owned profile endpoint');
assert.match(page, /不会写入 WordPress[\s\S]*普通 AI 积分[\s\S]*重建向量索引/, 'The rebuild action must preserve the Cloud and metering boundary in operator copy');
assert.match(page, /embedding_space_mismatch[\s\S]*全量 Site Knowledge 同步/, 'Mixed embedding spaces must direct the operator to a clean full sync instead of silent migration');
assert.match(page, /site_knowledge_vector_profile\.zilliz_sdk_unavailable[\s\S]*admin\.vector_settings\.zilliz_sdk_unavailable/, 'Vector storage must distinguish a missing server SDK from external connection failures');
assert.match(page, /admin\.vector_settings\.reindex_policy[\s\S]*admin\.vector_settings\.reindex_required/, 'Vector settings must retain the fixed profile reindex policy');
assert.match(page, /\/admin\/vector-observability/, 'Vector settings must link to the existing read-only diagnostics surface');
assert.doesNotMatch(page, /priority|channel note|通道备注/, 'Vector settings must not reintroduce channel priority or notes');
assert.doesNotMatch(page, /rerank_provider|Result reranking|结果重排|store_postgres|data-vector-group/, 'Vector settings must not restore the retired multi-provider configuration surface');
assert.match(layout, /href: '\/admin\/vector-settings'[\s\S]*activePrefixes: \['\/admin\/vector-settings'\]/, 'Admin navigation must expose Vector Settings under Runtime Plane');

console.log('admin_vector_settings_contract: ok');
