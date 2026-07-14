import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const pageSource = read('src/app/admin/ai-resources/page.tsx');
const externalServicesSource = read('src/app/admin/external-services/page.tsx');
const vectorSettingsSource = read('src/app/admin/vector-settings/page.tsx');
const layoutSource = read('src/app/admin/layout.tsx');
const toolbarSource = read('src/components/admin/SupplierToolbar.tsx');
const summarySource = read('src/components/admin/SupplierSummaryCards.tsx');
const tablesSource = read('src/components/admin/SupplierConnectionTables.tsx');
const i18nSource = read('src/lib/i18n.ts');

const aiResourcesNavIndex = layoutSource.indexOf("href: '/admin/ai-resources'");
const externalServicesNavIndex = layoutSource.indexOf("href: '/admin/external-services'");
const vectorSettingsNavIndex = layoutSource.indexOf("href: '/admin/vector-settings'");
const diagnosticsNavIndex = layoutSource.indexOf("href: '/admin/troubleshooting'");

assert.ok(aiResourcesNavIndex >= 0, 'Model suppliers must have a primary admin navigation entry');
assert.ok(externalServicesNavIndex > aiResourcesNavIndex, 'Search and images must follow model suppliers');
assert.ok(vectorSettingsNavIndex > externalServicesNavIndex, 'Vector settings must follow search and images');
assert.ok(diagnosticsNavIndex > vectorSettingsNavIndex, 'Runtime diagnostics must remain the final runtime-plane entry');
assert.match(layoutSource, /href: '\/admin\/ai-resources'[\s\S]*fallback: 'Model Suppliers'/);
assert.match(layoutSource, /href: '\/admin\/external-services'[\s\S]*fallback: 'Search & Images'/);
assert.match(i18nSource, /'admin\.nav_ai_resources': '模型供应商'/);
assert.match(i18nSource, /'admin\.nav_external_services': '搜索与图片'/);
assert.match(i18nSource, /'admin\.ai_resources\.title': '模型供应商'/);

assert.match(pageSource, /<SupplierToolbar[\s\S]*onAddModelSupplier=\{openNewProviderConnection\}/);
assert.match(pageSource, /<ModelSupplierTable[\s\S]*connections=\{aiSupplierConnections\}/);
assert.match(pageSource, /href="\/admin\/ability-models"[\s\S]*action_open_model_binding/);
assert.match(pageSource, /supplierCategory\(connection\) === 'ai'/);
assert.match(pageSource, /connection\.kind === 'embedding_provider'/);
assert.doesNotMatch(pageSource, /connection\.capability_ids\.includes\('embedding'\)/);
assert.doesNotMatch(pageSource, /CAPABILITY_PROVIDER_TEMPLATES|CapabilityProviderTemplate|CapabilitySupplierTable/);
assert.doesNotMatch(pageSource, /isCapabilityProviderForm|capabilityAddDialogOpen|supplierTypeFilter/);
assert.doesNotMatch(pageSource, /action_add_capability_supplier|capability_channel_form|capability_diagnostics/);
assert.doesNotMatch(pageSource, /runtime-telemetry|RuntimeTelemetrySummary|provider_model_health|capability_matrix/);
assert.doesNotMatch(pageSource, /providerConnectionForm\.(priority|note)|field_channel_priority|field_channel_note/);

assert.match(toolbarSource, /action_add_model_supplier/);
assert.doesNotMatch(toolbarSource, /SupplierTypeFilter|supplierTypeFilter|action_add_capability_supplier/);
assert.match(summarySource, /grid-cols-2/);
assert.doesNotMatch(summarySource, /readyCapabilitySupplierCount|capabilitySupplierCount/);
assert.match(tablesSource, /export function ModelSupplierTable/);
assert.doesNotMatch(tablesSource, /CapabilitySupplierTable|capability-supplier-directory|CapabilityProviderCategory/);

for (const providerId of ['tavily', 'bocha', 'apify', 'zhihu', 'jina_reader', 'unsplash', 'pixabay', 'pexels']) {
  assert.match(externalServicesSource, new RegExp(`id: '${providerId}'`), `${providerId} must remain a fixed external-service option`);
}
assert.match(externalServicesSource, /type ServiceCategory = 'search' \| 'image'/);
assert.match(externalServicesSource, /role: 'primary'/);
assert.match(externalServicesSource, /role: 'enhancer'[\s\S]*secretless: true/);
assert.match(externalServicesSource, /role: 'parallel'/);
assert.match(externalServicesSource, /One primary \+ Reader enhancement/);
assert.match(externalServicesSource, /Enabled sources in parallel/);
assert.match(externalServicesSource, /data-external-service-id=\{option\.id\}/);
assert.match(externalServicesSource, /readOnly value=\{option\.baseUrl\}/);
assert.match(externalServicesSource, /Clear credential and disable/);
assert.match(externalServicesSource, /\/api\/admin\/provider-connections/);
assert.match(externalServicesSource, /metadata: \{ ui_source: 'external_services', service_role: option\.role \}/);
assert.doesNotMatch(externalServicesSource, /priority|channel_note|Add capability supplier|Delete supplier/);

assert.match(vectorSettingsSource, /admin\.vector_settings\.provider_title/);
assert.match(vectorSettingsSource, /admin\.vector_settings\.store_title/);
assert.match(vectorSettingsSource, /site-knowledge-vector-profile\/vector-store/);
assert.match(vectorSettingsSource, /site_knowledge_zh_v1/);
assert.doesNotMatch(vectorSettingsSource, /rerank_provider|Result reranking|结果重排/);
assert.doesNotMatch(vectorSettingsSource, /field_channel_priority|field_channel_note/);

for (const retiredKey of [
  'action_add_capability_supplier',
  'capability_add_dialog_title',
  'capability_channel_form_title',
  'capability_directory_title',
  'supplier_filter_capability',
]) {
  assert.doesNotMatch(i18nSource, new RegExp(`admin\\.ai_resources\\.${retiredKey}`), `${retiredKey} must not remain in translations`);
}

for (const retiredPage of ['web-search', 'image-sources', 'wordpress-ai-routing']) {
  assert.equal(
    existsSync(resolve(process.cwd(), `src/app/admin/${retiredPage}/page.tsx`)),
    false,
    `${retiredPage} must not return as a parallel admin configuration surface`
  );
}

console.log('admin_ai_resources_contract: ok');
