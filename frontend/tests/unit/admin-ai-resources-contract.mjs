import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/ai-resources/page.tsx');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const troubleshootingPath = resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx');
const webSearchPagePath = resolve(process.cwd(), 'src/app/admin/web-search/page.tsx');
const imageSourcesPagePath = resolve(process.cwd(), 'src/app/admin/image-sources/page.tsx');
const pageSource = readFileSync(pagePath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const troubleshootingSource = readFileSync(troubleshootingPath, 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const openCapabilityTemplateStart = pageSource.indexOf('function openCapabilityProviderTemplate');
const openCapabilityTemplateSource = openCapabilityTemplateStart >= 0
  ? pageSource.slice(openCapabilityTemplateStart, pageSource.indexOf('const resourceStatusLabel', openCapabilityTemplateStart))
  : '';

const aiResourcesNavIndex = layoutSource.indexOf("href: '/admin/ai-resources'");
const troubleshootingNavIndex = layoutSource.indexOf("href: '/admin/troubleshooting'");
const troubleshootingNavBlock = layoutSource.slice(
  troubleshootingNavIndex,
  layoutSource.indexOf('const isPathMatch', troubleshootingNavIndex)
);

assert.ok(
  aiResourcesNavIndex >= 0,
  'AI resources must have a top-level admin navigation entry'
);

assert.ok(
  aiResourcesNavIndex < troubleshootingNavIndex,
  'AI resources must appear before Advanced Troubleshooting in primary navigation'
);

assert.doesNotMatch(
  troubleshootingNavBlock,
  /\/admin\/ai-resources/,
  'Advanced Troubleshooting must not own the AI resources active path'
);

assert.match(
  troubleshootingSource,
  /Related operations/,
  'Troubleshooting may expose AI resources only as a related operations link'
);

assert.match(
  troubleshootingSource,
  /Top-level model and capability supplier operations/,
  'Troubleshooting copy must explain provider management is a top-level operations entry'
);

assert.match(
  pageSource,
  /useLocale/,
  'AI resources page must use the shared locale system'
);

assert.match(
  pageSource,
  /admin\.ai_resources\./,
  'AI resources page must route static UI copy through admin.ai_resources translations'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.title': '供应商管理'/,
  'Provider management page must provide Simplified Chinese translations'
);

assert.match(
  i18nSource,
  /'admin\.nav_ai_resources': '供应商管理'/,
  'Top-level admin navigation must call the surface Provider Management in Simplified Chinese'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.window_last_24h': '最近 24 小时'/,
  'AI resources health windows must provide Simplified Chinese labels'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.status_missing_secret_label': '缺少密钥'/,
  'AI resources provider status labels must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.column_provider': '供应商'/,
  'AI resources provider table headings must provide Simplified Chinese copy'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/ai-resources'/,
  'AI resources page must read the shared admin AI resources projection'
);

assert.match(
  pageSource,
  /useState<AIResourceView>\('overview'\)/,
  'AI resources page must default to the low-noise overview'
);

assert.match(
  pageSource,
  /Operations overview/,
  'AI resources page must expose an operations overview'
);

assert.match(
  pageSource,
  /Daily provider readiness and diagnostic attention/,
  'AI resources overview must summarize daily provider readiness'
);

assert.match(
  pageSource,
  /Manage suppliers/,
  'Provider management overview must route primary work to supplier management'
);

assert.match(
  pageSource,
  /Overview actions open detail surfaces only/,
  'AI resources overview must keep actions as detail navigation only'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/ai-resources\/profile-preferences'/,
  'AI resources page must save only bounded profile preferences through the admin projection'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/provider-connections'/,
  'AI resources page must save provider connections through the bounded admin endpoint'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/provider-connections\/preview-catalog'/,
  'AI resources page must preview upstream models through the bounded provider catalog preview endpoint'
);

assert.match(
  pageSource,
  /action_fetch_upstream_models/,
  'Provider channel form must expose a fetch-from-upstream models action'
);

assert.match(
  pageSource,
  /providerCatalogPreview/,
  'Provider channel form must show upstream model preview state'
);

assert.match(
  pageSource,
  /PROVIDER_PRESETS/,
  'AI resources provider form must expose provider presets instead of requiring raw identifiers first'
);

assert.match(
  pageSource,
  /Add provider channel/,
  'AI resources provider form must be framed as adding a provider channel'
);

assert.match(
  pageSource,
  /providerFormOpen/,
  'AI resources provider form must stay hidden until the operator opens it'
);

assert.match(
  pageSource,
  /role="dialog"/,
  'AI resources provider form must open as an explicit dialog'
);

assert.match(
  pageSource,
  /Add provider/,
  'AI resources connections view must expose a compact add-provider action'
);

assert.match(
  pageSource,
  /Provider channels/,
  'AI resources connections view must list provider channels as the main working surface'
);

assert.match(
  pageSource,
  /connectionSearch/,
  'AI resources provider channel list must support search'
);

assert.match(
  pageSource,
  /connectionStatusFilter/,
  'AI resources provider channel list must support status filtering'
);

assert.match(
  pageSource,
  /SupplierSettingsTab/,
  'Provider management must split model suppliers and capability suppliers into operator tabs'
);

assert.match(
  pageSource,
  /CapabilityProviderCategory/,
  'Capability supplier management must model search, image, and vector categories explicitly'
);

assert.match(
  pageSource,
  /capabilityProviderCategory/,
  'Capability supplier rows must be classified before display'
);

assert.match(
  pageSource,
  /capabilityConnectionsByCategory/,
  'Capability suppliers must be grouped by category for operator scanning'
);

assert.match(
  pageSource,
  /CAPABILITY_PROVIDER_TEMPLATES/,
  'Capability supplier add flow must use built-in provider templates'
);

assert.match(
  pageSource,
  /capabilityAddDialogOpen/,
  'Capability supplier add flow must open an explicit template dialog'
);

assert.match(
  pageSource,
  /openCapabilityProviderTemplate/,
  'Choosing a capability supplier template must route to provider configuration'
);

assert.match(
  pageSource,
  /setProviderConnectionForm\(\{/,
  'Capability supplier templates must prefill the DB-managed provider connection form'
);

assert.match(
  pageSource,
  /kind: template\.kind/,
  'Capability supplier templates must preserve provider kind for runtime DB projection'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityProviderTemplate/,
  'Capability supplier configuration must not use the old env-backed provider settings dialog'
);

assert.match(
  pageSource,
  /id: 'apify'/,
  'Capability supplier templates must include Apify as a built-in search supplier'
);

assert.doesNotMatch(
  openCapabilityTemplateSource,
  /fetch|provider-connections/,
  'Capability supplier add flow must not create dynamic provider connection rows'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityPanel === 'search'/,
  'Web-search provider configuration must not open the whole search provider panel from the list'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityPanel === 'image'/,
  'Image-source provider configuration must not open the whole image provider panel from the list'
);

assert.match(
  pageSource,
  /activeCapabilityPanel === 'vector'/,
  'Vector supplier detail must remain visible as a category-specific summary'
);

assert.match(
  pageSource,
  /vector_store_provider/,
  'Provider management must support vector store provider connections'
);

assert.match(
  pageSource,
  /rerank_provider/,
  'Provider management must support rerank provider connections'
);

assert.doesNotMatch(
  pageSource,
  /WebSearchProviderSettings|ImageSourceProviderSettings/,
  'Capability suppliers must use DB-managed provider connections instead of env-backed settings components'
);

assert.doesNotMatch(
  layoutSource,
  /\/admin\/web-search|\/admin\/image-sources/,
  'Old capability provider pages must not remain admin navigation targets'
);

assert.doesNotMatch(
  troubleshootingSource,
  /href: '\/admin\/web-search'|href: '\/admin\/image-sources'/,
  'Advanced Troubleshooting must not link to retired capability provider pages'
);

assert.equal(
  existsSync(webSearchPagePath),
  false,
  'Web Search settings page must be removed after moving into Provider Management'
);

assert.equal(
  existsSync(imageSourcesPagePath),
  false,
  'Image Sources settings page must be removed after moving into Provider Management'
);

assert.doesNotMatch(
  pageSource,
  /\/api\/admin\/web-search-providers|\/api\/admin\/image-source-providers/,
  'Provider Management must not call retired env-backed capability provider APIs'
);

assert.match(
  pageSource,
  /supplierCategory/,
  'AI resources provider channel list must distinguish AI suppliers from capability suppliers'
);

assert.match(
  pageSource,
  /aiSupplierConnections/,
  'AI resources provider channel list must render AI suppliers separately'
);

assert.match(
  pageSource,
  /capabilitySupplierConnections/,
  'AI resources provider channel list must render capability suppliers separately'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_supplier_list_title': '能力供应商列表'/,
  'Capability supplier list must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_search': '搜索'/,
  'Capability supplier search category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_image': '图片'/,
  'Capability supplier image category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_vector': '向量'/,
  'Capability supplier vector category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.action_add_capability_supplier': '添加能力供应商'/,
  'Capability supplier add action must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_add_dialog_desc': '已存在的供应商不会重复新增/,
  'Capability supplier add dialog must explain built-in suppliers are not duplicated'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.message_capability_provider_template_existing': '\{\{name\}\} 已存在/,
  'Capability supplier template selection must explain it opens existing configuration'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.web_search_title': '搜索供应商'/,
  'Moved web-search settings must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.image_source_title': '图片供应商'/,
  'Moved image-source settings must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.kind_rerank_provider': '重排提供商'/,
  'Capability supplier vector detail must translate rerank providers'
);

assert.match(
  pageSource,
  /isAiSupplier \? \(/,
  'AI resources provider edit/test/delete actions must be limited to AI suppliers'
);

assert.match(
  pageSource,
  /action_open_config/,
  'AI resources capability supplier rows must use a distinct open-config action'
);

assert.match(
  pageSource,
  /resourceStatusLabel/,
  'AI resources provider channel list must translate raw runtime statuses for operators'
);

assert.match(
  pageSource,
  /providerKindLabel/,
  'AI resources provider channel list must translate provider kinds for operators'
);

assert.match(
  pageSource,
  /<table className="min-w-\[1120px\]/,
  'AI resources provider channels must render as a compact table instead of large cards'
);

assert.match(
  pageSource,
  /Enabled \/ configured/,
  'AI resources provider channel table must expose enabled and configured state in one scannable column'
);

assert.doesNotMatch(
  pageSource,
  /data\.env_migration && data\.env_migration\.importable_source_count > 0/,
  'AI resources page must not keep env migration as an operator workflow'
);

assert.doesNotMatch(
  pageSource,
  /<BackofficeStackCard key=\{connection\.connection_id\}/,
  'AI resources provider channels must not regress to repeated large cards'
);

assert.match(
  pageSource,
  /Save and test provider/,
  'AI resources provider form must save and test in one primary action'
);

assert.match(
  pageSource,
  /Advanced runtime settings/,
  'AI resources provider form must keep raw runtime fields behind an advanced disclosure'
);

assert.match(
  pageSource,
  /runProviderConnectionTest\(savedConnectionId/,
  'AI resources provider save must automatically test the saved provider connection'
);

assert.match(
  pageSource,
  /model_ids: modelIds/,
  'AI resources provider form must preserve manually entered model ids as runtime metadata'
);

assert.match(
  pageSource,
  /provider-connections\/.*\/test/,
  'AI resources page must test managed provider connections through the bounded admin endpoint'
);

assert.doesNotMatch(
  pageSource,
  /provider-connections\/import-env/,
  'AI resources page must not expose env provider import after DB-managed provider migration'
);

assert.match(
  pageSource,
  /Provider connections can be managed in Cloud runtime storage/,
  'AI resources page must explain provider connections are managed by Cloud runtime storage'
);

assert.match(
  pageSource,
  /WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page/,
  'AI resources page must not present itself as a second control plane'
);

assert.match(
  pageSource,
  /Recent runtime evidence/,
  'AI resources page must expose recent runtime evidence for operator debugging'
);

assert.match(
  pageSource,
  /Capability Matrix/,
  'AI resources page must expose the capability-to-provider-model matrix'
);

assert.match(
  pageSource,
  /Runtime resolution/,
  'AI resources page must expose the current runtime resolution'
);

assert.match(
  pageSource,
  /Feature usage/,
  'AI resources page must expose feature-to-model usage'
);

assert.match(
  pageSource,
  /Model health/,
  'AI resources page must expose provider-model health diagnostics'
);

assert.match(
  pageSource,
  /Last 24h/,
  'Model health must expose a short diagnostic window'
);

assert.match(
  pageSource,
  /Last 7d/,
  'Model health must expose a longer diagnostic window'
);

assert.match(
  pageSource,
  /Feature-to-model evidence from Cloud runtime metadata/,
  'Feature usage must be framed as runtime metadata evidence'
);

assert.match(
  pageSource,
  /does not change routing, prompts, abilities, or WordPress writes/,
  'Feature usage must remain read-only and outside control-plane truth'
);

assert.match(
  pageSource,
  /Provider\/model health from provider_call_records/,
  'Model health must be backed by provider call metadata'
);

assert.match(
  pageSource,
  /Metadata only: prompts, results, and provider secrets are not exposed/,
  'Model health must not expose prompt, result, or secret material'
);

assert.match(
  pageSource,
  /Health alerts are diagnostic only and do not change routing, prompts, abilities, or WordPress writes/,
  'Model health must remain diagnostics-only'
);

assert.match(
  pageSource,
  /read-only diagnostics/,
  'Model health alerts must be framed as read-only diagnostics'
);

assert.match(
  pageSource,
  /read-only operator evidence, not a router editor/,
  'AI resources runtime resolution must not present itself as a router editor'
);

assert.doesNotMatch(
  pageSource,
  /Environment migration/,
  'AI resources page must not keep environment-to-DB migration UI after import is complete'
);

assert.doesNotMatch(
  pageSource,
  /Environment values remain fallback only/,
  'AI resources page must not teach operators to manage AI channels through environment fallback'
);

assert.match(
  pageSource,
  /Cloud runtime mapping from capability to profile, provider, model, and write posture/,
  'AI resources matrix must explain the runtime mapping purpose'
);

assert.match(
  pageSource,
  /not a WordPress ability editor/,
  'AI resources matrix must not present itself as a local ability editor'
);

assert.match(
  pageSource,
  /field_enabled/,
  'AI resources connections view must expose provider enabled state'
);

assert.match(
  pageSource,
  /field_configured/,
  'AI resources connections view must expose masked provider configured state'
);

assert.match(
  pageSource,
  /last_test/,
  'AI resources connections view must expose masked provider test diagnostics'
);

assert.match(
  pageSource,
  /setProviderFormOpen\(true\)/,
  'AI resources edit action must open the provider form dialog'
);

assert.match(
  pageSource,
  /Credential is left blank unless you replace it/,
  'AI resources edit action must explain masked credential behavior'
);

assert.match(
  pageSource,
  /Prompt and result content are not exposed here/,
  'AI resources runtime evidence must be metadata-only'
);

assert.doesNotMatch(
  pageSource,
  /secret:\s*string/,
  'AI resources page must not model raw provider secrets'
);

assert.doesNotMatch(
  pageSource,
  /api_key|group_id/,
  'AI resources page must not expose provider credential fields'
);

assert.doesNotMatch(
  pageSource,
  /auto[- ]?apply|auto[- ]?switch|switch model/i,
  'AI resources page must not expose automatic model routing controls'
);

console.log('admin_ai_resources_contract: ok');
