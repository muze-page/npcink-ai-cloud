'use client';

import Link from 'next/link';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AdminRouteSkeleton } from '@/components/admin/AdminRouteSkeleton';
import {
  BackofficeDiagnosticNotice,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';

type ServiceCategory = 'search' | 'image';

const externalServicesClient = createApiClient({ idempotencyPrefix: 'external_services' });

type ProviderConnection = {
  connection_id: string;
  provider_id: string;
  provider_type: string;
  kind: string;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  status: string;
  base_url: string;
  source_role: string;
  capability_ids: string[];
  runtime_profile_ids: string[];
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

type ServiceOption = {
  id: string;
  category: ServiceCategory;
  label: string;
  description: string;
  descriptionZh: string;
  kind: 'web_search_provider' | 'image_source_provider';
  baseUrl: string;
  capabilityIds: string[];
  runtimeProfileIds: string[];
  role: 'primary' | 'enhancer' | 'parallel';
  secretless?: boolean;
};

const SERVICE_OPTIONS: ServiceOption[] = [
  { id: 'tavily', category: 'search', label: 'Tavily', description: 'Primary general web search.', descriptionZh: '通用网页搜索主服务。', kind: 'web_search_provider', baseUrl: 'https://api.tavily.com', capabilityIds: ['web_search'], runtimeProfileIds: ['web-search.managed'], role: 'primary' },
  { id: 'bocha', category: 'search', label: 'Bocha', description: 'Primary search service for Chinese and public sources.', descriptionZh: '面向中文和公开来源的主搜索服务。', kind: 'web_search_provider', baseUrl: 'https://api.bochaai.com/v1', capabilityIds: ['web_search'], runtimeProfileIds: ['web-search.managed'], role: 'primary' },
  { id: 'apify', category: 'search', label: 'Apify', description: 'Primary actor-backed search service.', descriptionZh: '基于 Actor 的主搜索服务。', kind: 'web_search_provider', baseUrl: 'https://api.apify.com/v2', capabilityIds: ['web_search'], runtimeProfileIds: ['web-search.managed'], role: 'primary' },
  { id: 'zhihu', category: 'search', label: 'Zhihu Search', description: 'Primary Zhihu Open Platform search.', descriptionZh: '知乎开放平台主搜索服务。', kind: 'web_search_provider', baseUrl: 'https://developer.zhihu.com', capabilityIds: ['web_search'], runtimeProfileIds: ['web-search.managed'], role: 'primary' },
  { id: 'jina_reader', category: 'search', label: 'Jina Reader', description: 'Optional result-page reader enhancement; it is not a primary search service.', descriptionZh: '可选的结果页读取增强，不作为主搜索服务。', kind: 'web_search_provider', baseUrl: 'https://r.jina.ai', capabilityIds: ['web_search'], runtimeProfileIds: ['web-search.reader'], role: 'enhancer', secretless: true },
  { id: 'unsplash', category: 'image', label: 'Unsplash', description: 'Stock image source used in parallel with other enabled sources.', descriptionZh: '可与其他已启用来源并行使用的图库。', kind: 'image_source_provider', baseUrl: 'https://api.unsplash.com', capabilityIds: ['image_source'], runtimeProfileIds: ['image-source.managed'], role: 'parallel' },
  { id: 'pixabay', category: 'image', label: 'Pixabay', description: 'Stock image source used in parallel with other enabled sources.', descriptionZh: '可与其他已启用来源并行使用的图库。', kind: 'image_source_provider', baseUrl: 'https://pixabay.com/api', capabilityIds: ['image_source'], runtimeProfileIds: ['image-source.managed'], role: 'parallel' },
  { id: 'pexels', category: 'image', label: 'Pexels', description: 'Stock image source used in parallel with other enabled sources.', descriptionZh: '可与其他已启用来源并行使用的图库。', kind: 'image_source_provider', baseUrl: 'https://api.pexels.com/v1', capabilityIds: ['image_source'], runtimeProfileIds: ['image-source.managed'], role: 'parallel' },
];

function connectionFor(option: ServiceOption, connections: ProviderConnection[]) {
  return connections.find((connection) => connection.kind === option.kind && connection.provider_id === option.id);
}

export default function ExternalServicesPage() {
  const { locale, t } = useLocale();
  const zh = locale.startsWith('zh');
  const copy = useCallback((key: string, zhText: string, enText: string) => t(key, {}, zh ? zhText : enText), [t, zh]);
  const [category, setCategory] = useState<ServiceCategory>('search');
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadConnections = useCallback(async () => {
    setError('');
    try {
      const response = await externalServicesClient.request<{ connections?: ProviderConnection[] }>(
        '/api/admin/provider-connections'
      );
      setConnections(Array.isArray(response.data.connections) ? response.data.connections : []);
    } catch (loadError) {
      setError(resolveUiErrorMessage(loadError, copy('admin.external_services.load_error', '加载外部服务失败。', 'Failed to load external services.')));
    } finally {
      setLoading(false);
    }
  }, [copy]);

  useEffect(() => { void loadConnections(); }, [loadConnections]);

  const visibleOptions = useMemo(() => SERVICE_OPTIONS.filter((option) => option.category === category), [category]);
  const readyCount = SERVICE_OPTIONS.filter((option) => {
    const connection = connectionFor(option, connections);
    return Boolean(connection?.enabled && (connection.configured || option.secretless));
  }).length;

  async function saveOption(option: ServiceOption, enabled: boolean, clearCredential = false) {
    const existing = connectionFor(option, connections);
    const credential = clearCredential ? '' : credentials[option.id] || undefined;
    if (enabled && !option.secretless && !credential && !existing?.configured) {
      setError(copy('admin.external_services.credential_required', '启用前请填写 API Key 或 Token。', 'Enter an API key or token before enabling this service.'));
      return;
    }
    setBusy(`${clearCredential ? 'clear' : 'save'}:${option.id}`);
    setError('');
    setMessage('');
    try {
      await externalServicesClient.request<unknown>(
        existing ? `/api/admin/provider-connections/${encodeURIComponent(existing.connection_id)}` : '/api/admin/provider-connections',
        {
          method: existing ? 'PATCH' : 'POST',
          body: {
            connection_id: existing?.connection_id || `external_${option.id}`,
            provider_id: option.id,
            provider_type: option.kind,
            kind: option.kind,
            display_name: option.label,
            enabled: clearCredential ? false : enabled,
            base_url: option.baseUrl,
            source_role: option.role === 'enhancer' ? 'reader_enhancement' : 'execution_source',
            capability_ids: option.capabilityIds,
            runtime_profile_ids: option.runtimeProfileIds,
            config: { ...(existing?.config || {}), secretless: Boolean(option.secretless) },
            metadata: { ui_source: 'external_services', service_role: option.role },
            secretless: Boolean(option.secretless),
            credential,
          },
        }
      );
      setCredentials((current) => ({ ...current, [option.id]: '' }));
      setMessage(clearCredential
        ? copy('admin.external_services.cleared', '凭据已清除，服务已停用。', 'Credential cleared and service disabled.')
        : copy('admin.external_services.saved', '外部服务设置已保存。', 'External service settings saved.'));
      await loadConnections();
    } catch (saveError) {
      setError(resolveUiErrorMessage(saveError, copy('admin.external_services.save_error', '保存外部服务失败。', 'Failed to save external service.')));
    } finally {
      setBusy('');
    }
  }

  async function testOption(option: ServiceOption) {
    const connection = connectionFor(option, connections);
    if (!connection) return;
    setBusy(`test:${option.id}`);
    setError('');
    setMessage('');
    try {
      await externalServicesClient.request<unknown>(
        `/api/admin/provider-connections/${encodeURIComponent(connection.connection_id)}/test`,
        { method: 'POST' }
      );
      setMessage(copy('admin.external_services.test_passed', '连接测试通过。', 'Connection test passed.'));
      await loadConnections();
    } catch (testError) {
      setError(resolveUiErrorMessage(testError, copy('admin.external_services.test_error', '连接测试失败。', 'Connection test failed.')));
    } finally {
      setBusy('');
    }
  }

  if (loading) return <AdminRouteSkeleton />;

  return (
    <BackofficePageStack data-page-model="configuration" data-external-services-page>
      <BackofficePrimaryPanel
        eyebrow={copy('admin.external_services.eyebrow', '运行设置', 'Runtime settings')}
        title={copy('admin.external_services.title', '搜索与图片', 'Search & images')}
        description={copy('admin.external_services.description', '从固定服务清单配置网页搜索和图库来源，无需创建供应商记录。', 'Configure web search and stock-image sources from a fixed service directory; no supplier records need to be created.')}
        actions={<Link href="/admin/troubleshooting" className="btn btn-secondary">{copy('admin.external_services.open_diagnostics', '查看运行诊断', 'Open runtime diagnostics')}</Link>}
        summary={<BackofficeSummaryStrip items={[
          { label: copy('admin.external_services.ready', '已就绪服务', 'Ready services'), value: `${readyCount}/${SERVICE_OPTIONS.length}` },
          { label: copy('admin.external_services.search_rule', '搜索规则', 'Search rule'), value: copy('admin.external_services.search_rule_value', '主服务单选 + Reader 增强', 'One primary + Reader enhancement') },
          { label: copy('admin.external_services.image_rule', '图片规则', 'Image rule'), value: copy('admin.external_services.image_rule_value', '已启用来源并行', 'Enabled sources in parallel') },
        ]} />}
      >
        <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{copy('admin.external_services.boundary', '这里只配置 Cloud 运行时外部服务，不定义 WordPress 能力、工作流或写入权限。', 'This page configures Cloud runtime services only; it does not define WordPress abilities, workflows, or write authority.')}</p>
      </BackofficePrimaryPanel>

      {error ? <BackofficeDiagnosticNotice message={error} retryLabel={copy('common.retry', '重试', 'Retry')} onRetry={() => void loadConnections()} /> : null}
      {message ? <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">{message}</p> : null}

      <BackofficeSectionPanel>
        <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-4 dark:border-slate-800" role="tablist" aria-label={copy('admin.external_services.categories', '服务类型', 'Service category')}>
          {(['search', 'image'] as ServiceCategory[]).map((value) => (
            <button key={value} type="button" role="tab" aria-selected={category === value} className={category === value ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'} onClick={() => setCategory(value)}>
              {value === 'search' ? copy('admin.external_services.search', '网页搜索', 'Web search') : copy('admin.external_services.images', '图库来源', 'Image sources')}
            </button>
          ))}
        </div>
        <div className="mt-4 space-y-4" data-external-category={category}>
          {visibleOptions.map((option) => {
            const connection = connectionFor(option, connections);
            const enabled = Boolean(connection?.enabled);
            const ready = enabled && Boolean(connection?.configured || option.secretless);
            return (
              <section key={option.id} data-external-service-id={option.id} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/45">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold text-slate-950 dark:text-white">{option.label}</h2><BackofficeStatusBadge label={ready ? copy('common.ready', '已就绪', 'Ready') : enabled ? copy('common.missing_config', '缺少凭据', 'Missing credential') : copy('common.disabled', '已停用', 'Disabled')} status={ready ? 'success' : enabled ? 'warning' : 'neutral'} /></div>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{zh ? option.descriptionZh : option.description}</p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{option.role === 'primary' ? copy('admin.external_services.primary_role', '主搜索候选；启用后替换其他主搜索服务。', 'Primary search candidate; enabling it replaces the other primary search service.') : option.role === 'enhancer' ? copy('admin.external_services.enhancer_role', '独立增强项，可与主搜索服务同时启用。', 'Independent enhancement that can run alongside the primary search service.') : copy('admin.external_services.parallel_role', '独立来源，可与其他图库同时启用。', 'Independent source that can run alongside other image sources.')}</p>
                  </div>
                  <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200"><input type="checkbox" checked={enabled} disabled={busy !== ''} onChange={(event) => void saveOption(option, event.target.checked)} />{copy('common.enabled', '启用', 'Enabled')}</label>
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.external_services.service_url', '服务地址', 'Service URL')}<input readOnly value={option.baseUrl} className="h-11 rounded-lg border border-slate-200 bg-slate-100 px-3 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300" /></label>
                  <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.external_services.credential', 'API Key / Token', 'API key / token')}<input type="password" autoComplete="new-password" value={credentials[option.id] || ''} onChange={(event) => setCredentials((current) => ({ ...current, [option.id]: event.target.value }))} placeholder={connection?.configured ? copy('admin.external_services.keep_credential', '留空则保留已保存凭据', 'Leave blank to keep saved credential') : option.secretless ? copy('admin.external_services.optional', '可选', 'Optional') : ''} className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" /></label>
                </div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <details className="text-xs text-slate-500 dark:text-slate-400"><summary className="cursor-pointer">{copy('admin.external_services.advanced', '高级操作', 'Advanced')}</summary><button type="button" className="mt-2 text-red-600 hover:underline disabled:opacity-50 dark:text-red-400" disabled={!connection?.configured || busy !== ''} onClick={() => void saveOption(option, false, true)}>{copy('admin.external_services.clear_credential', '清除凭据并停用', 'Clear credential and disable')}</button></details>
                  <div className="flex gap-2">{connection?.configured ? <button type="button" className="btn btn-secondary btn-sm" disabled={busy !== ''} onClick={() => void testOption(option)}>{busy === `test:${option.id}` ? copy('common.testing', '测试中…', 'Testing…') : copy('common.test_connection', '测试连接', 'Test connection')}</button> : null}<button type="button" className="btn btn-primary btn-sm" disabled={busy !== ''} onClick={() => void saveOption(option, enabled)}>{busy === `save:${option.id}` ? copy('common.saving', '保存中…', 'Saving…') : copy('common.save', '保存', 'Save')}</button></div>
                </div>
              </section>
            );
          })}
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}
