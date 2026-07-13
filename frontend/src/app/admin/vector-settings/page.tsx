'use client';

import Link from 'next/link';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BackofficeDiagnosticNotice,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { AdminRouteSkeleton } from '@/components/admin/AdminRouteSkeleton';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';

type VectorGroup = 'embedding' | 'store' | 'rerank';

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
  last_tested_at?: string;
};

type VectorOption = {
  id: string;
  group: VectorGroup;
  label: string;
  labelZh?: string;
  description: string;
  descriptionZh: string;
  providerId?: string;
  kind?: string;
  baseUrl?: string;
  capabilityIds?: string[];
  runtimeProfileIds?: string[];
  modelId?: string;
  dimensions?: number;
  secretless?: boolean;
};

type VectorDraft = {
  baseUrl: string;
  credential: string;
  modelId: string;
  dimensions: string;
  database: string;
  collection: string;
  topK: string;
};

const GROUP_KINDS: Record<VectorGroup, string> = {
  embedding: 'embedding_provider',
  store: 'vector_store_provider',
  rerank: 'rerank_provider',
};

const VECTOR_OPTIONS: VectorOption[] = [
  {
    id: 'embedding_openai',
    group: 'embedding',
    label: 'OpenAI-compatible Embedding',
    labelZh: 'OpenAI 兼容 Embedding',
    description: 'Use a fixed OpenAI-compatible embeddings endpoint.',
    descriptionZh: '使用固定的 OpenAI 兼容 Embedding 接口。',
    providerId: 'openai',
    kind: 'embedding_provider',
    baseUrl: 'https://api.openai.com/v1',
    capabilityIds: ['embedding'],
    runtimeProfileIds: ['embed.default'],
    modelId: 'text-embedding-3-small',
    dimensions: 1536,
  },
  {
    id: 'embedding_siliconflow',
    group: 'embedding',
    label: 'SiliconFlow Embedding',
    description: 'Managed embedding service with BGE-compatible models.',
    descriptionZh: '使用支持 BGE 系列模型的托管 Embedding 服务。',
    providerId: 'siliconflow',
    kind: 'embedding_provider',
    baseUrl: 'https://api.siliconflow.cn/v1',
    capabilityIds: ['embedding'],
    runtimeProfileIds: ['embed.default'],
    modelId: 'BAAI/bge-m3',
    dimensions: 1024,
  },
  {
    id: 'embedding_tei',
    group: 'embedding',
    label: 'Text Embeddings Inference',
    description: 'Self-hosted TEI endpoint. Credentials are optional.',
    descriptionZh: '使用自托管 TEI 接口，凭据可选。',
    providerId: 'tei',
    kind: 'embedding_provider',
    baseUrl: 'http://tei:80',
    capabilityIds: ['embedding'],
    runtimeProfileIds: ['embed.default'],
    modelId: 'BAAI/bge-m3',
    dimensions: 1024,
    secretless: true,
  },
  {
    id: 'store_postgres',
    group: 'store',
    label: 'Built-in PostgreSQL storage',
    labelZh: '内置 PostgreSQL 存储',
    description: 'Keep vector data in the Cloud database without an external vector service.',
    descriptionZh: '向量数据保存在 Cloud 数据库中，不依赖外部向量服务。',
  },
  {
    id: 'store_zilliz',
    group: 'store',
    label: 'Zilliz Cloud',
    description: 'Use a managed vector database for Site Knowledge storage and retrieval.',
    descriptionZh: '使用托管向量数据库保存和检索站点知识。',
    providerId: 'zilliz',
    kind: 'vector_store_provider',
    baseUrl: '',
    capabilityIds: ['vector_store'],
    runtimeProfileIds: ['site-knowledge.vector-store'],
  },
  {
    id: 'rerank_disabled',
    group: 'rerank',
    label: 'Disabled',
    labelZh: '关闭',
    description: 'Return vector-search ordering without a second-stage reranker.',
    descriptionZh: '直接使用向量检索排序，不执行第二阶段重排。',
  },
  {
    id: 'rerank_jina',
    group: 'rerank',
    label: 'Jina Rerank',
    description: 'Rerank Site Knowledge results after vector retrieval.',
    descriptionZh: '在向量检索后重新排序站点知识结果。',
    providerId: 'jina',
    kind: 'rerank_provider',
    baseUrl: 'https://api.jina.ai',
    capabilityIds: ['site_knowledge_rerank'],
    runtimeProfileIds: ['site-knowledge.rerank'],
    modelId: 'jina-reranker-v3',
  },
];

const EMPTY_DRAFT: VectorDraft = {
  baseUrl: '',
  credential: '',
  modelId: '',
  dimensions: '',
  database: '',
  collection: 'site_knowledge_chunks',
  topK: '20',
};

function optionForConnection(connection: ProviderConnection | undefined): VectorOption | undefined {
  if (!connection) return undefined;
  return VECTOR_OPTIONS.find(
    (option) => option.kind === connection.kind && option.providerId === connection.provider_id
  );
}

function draftForOption(option: VectorOption, connection?: ProviderConnection): VectorDraft {
  const config = connection?.config || {};
  return {
    ...EMPTY_DRAFT,
    baseUrl: connection?.base_url || option.baseUrl || '',
    modelId: String(config.model_id || option.modelId || ''),
    dimensions: String(config.dimensions || option.dimensions || ''),
    database: String(config.database || ''),
    collection: String(config.collection || 'site_knowledge_chunks'),
    topK: String(config.top_k || '20'),
  };
}

export default function VectorSettingsPage() {
  const { locale, t } = useLocale();
  const zh = locale.startsWith('zh');
  const copy = useCallback((key: string, zhText: string, enText: string) => (
    t(key, {}, zh ? zhText : enText)
  ), [t, zh]);
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingGroup, setSavingGroup] = useState<VectorGroup | ''>('');
  const [testingGroup, setTestingGroup] = useState<VectorGroup | ''>('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [selection, setSelection] = useState<Record<VectorGroup, string>>({
    embedding: '',
    store: 'store_postgres',
    rerank: 'rerank_disabled',
  });
  const [drafts, setDrafts] = useState<Record<VectorGroup, VectorDraft>>({
    embedding: EMPTY_DRAFT,
    store: EMPTY_DRAFT,
    rerank: EMPTY_DRAFT,
  });

  const loadConnections = useCallback(async () => {
    setError('');
    try {
      const response = await fetch('/api/admin/provider-connections', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, copy('admin.vector_settings.load_error', '加载向量设置失败。', 'Failed to load vector settings.')));
      }
      const nextConnections = Array.isArray(payload?.data?.connections)
        ? payload.data.connections as ProviderConnection[]
        : [];
      setConnections(nextConnections);
      const nextSelection: Record<VectorGroup, string> = {
        embedding: '',
        store: 'store_postgres',
        rerank: 'rerank_disabled',
      };
      const nextDrafts: Record<VectorGroup, VectorDraft> = {
        embedding: EMPTY_DRAFT,
        store: EMPTY_DRAFT,
        rerank: EMPTY_DRAFT,
      };
      (Object.keys(GROUP_KINDS) as VectorGroup[]).forEach((group) => {
        const groupConnections = nextConnections.filter(
          (connection) => connection.enabled && connection.kind === GROUP_KINDS[group]
        );
        const active = groupConnections.find((connection) => connection.configured)
          || groupConnections[0];
        const option = optionForConnection(active);
        if (option) {
          nextSelection[group] = option.id;
          nextDrafts[group] = draftForOption(option, active);
        }
      });
      setSelection(nextSelection);
      setDrafts(nextDrafts);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : copy('admin.vector_settings.load_error', '加载向量设置失败。', 'Failed to load vector settings.'));
    } finally {
      setLoading(false);
    }
  }, [copy]);

  useEffect(() => {
    void loadConnections();
  }, [loadConnections]);

  const activeConnections = useMemo(() => {
    const activeForGroup = (group: VectorGroup) => {
      const rows = connections.filter(
        (connection) => connection.enabled && connection.kind === GROUP_KINDS[group]
      );
      return rows.find((connection) => connection.configured) || rows[0];
    };
    return {
      embedding: activeForGroup('embedding'),
      store: activeForGroup('store'),
      rerank: activeForGroup('rerank'),
    };
  }, [connections]);

  function chooseOption(group: VectorGroup, option: VectorOption) {
    const existing = connections.find(
      (connection) => connection.kind === option.kind && connection.provider_id === option.providerId
    );
    setSelection((current) => ({ ...current, [group]: option.id }));
    setDrafts((current) => ({ ...current, [group]: draftForOption(option, existing) }));
    setMessage('');
    setError('');
  }

  function updateDraft(group: VectorGroup, patch: Partial<VectorDraft>) {
    setDrafts((current) => ({ ...current, [group]: { ...current[group], ...patch } }));
  }

  async function setConnectionEnabled(connection: ProviderConnection, enabled: boolean) {
    const response = await fetch(`/api/admin/provider-connections/${encodeURIComponent(connection.connection_id)}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        connection_id: connection.connection_id,
        provider_id: connection.provider_id,
        provider_type: connection.provider_type,
        kind: connection.kind,
        display_name: connection.display_name,
        enabled,
        base_url: connection.base_url,
        source_role: connection.source_role || 'execution_source',
        capability_ids: connection.capability_ids,
        runtime_profile_ids: connection.runtime_profile_ids,
        config: connection.config || {},
        metadata: connection.metadata || {},
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(resolveUiErrorMessage(payload, copy('admin.vector_settings.save_error', '保存向量设置失败。', 'Failed to save vector settings.')));
  }

  async function saveGroup(group: VectorGroup) {
    const option = VECTOR_OPTIONS.find((item) => item.id === selection[group]);
    if (!option) {
      setError(copy('admin.vector_settings.choose_option', '请先选择一个固定配置选项。', 'Choose a fixed configuration option first.'));
      return;
    }
    const draft = drafts[group];
    const existing = option.kind && option.providerId
      ? connections.find(
          (connection) => connection.kind === option.kind && connection.provider_id === option.providerId
        )
      : undefined;
    if (option.kind && !option.secretless && !draft.credential && !existing?.configured) {
      setError(copy('admin.vector_settings.credential_required', '请先填写 API Key 或 Token。', 'Enter an API key or token before saving.'));
      return;
    }
    if (group === 'embedding' && (!draft.modelId.trim() || Number(draft.dimensions) <= 0)) {
      setError(copy('admin.vector_settings.embedding_required', 'Embedding 模型和向量维度不能为空。', 'Embedding model and vector dimensions are required.'));
      return;
    }
    if (option.id === 'store_zilliz' && (!draft.baseUrl.trim() || !draft.collection.trim())) {
      setError(copy('admin.vector_settings.store_required', 'Zilliz 地址和 Collection 不能为空。', 'Zilliz URL and collection are required.'));
      return;
    }
    setSavingGroup(group);
    setError('');
    setMessage('');
    try {
      if (!option.kind || !option.providerId) {
        const enabledRows = connections.filter(
          (connection) => connection.enabled && connection.kind === GROUP_KINDS[group]
        );
        for (const connection of enabledRows) await setConnectionEnabled(connection, false);
      } else {
        const config: Record<string, unknown> = {};
        if (group === 'embedding') {
          config.model_id = draft.modelId.trim();
          config.model_ids = [draft.modelId.trim()];
          config.site_knowledge_model_id = draft.modelId.trim();
          config.dimensions = Number(draft.dimensions);
        } else if (group === 'store') {
          config.uri = draft.baseUrl.trim();
          config.database = draft.database.trim();
          config.collection = draft.collection.trim();
        } else {
          config.model_id = draft.modelId.trim();
          config.top_k = Number(draft.topK) || 20;
        }
        const response = await fetch(
          existing
            ? `/api/admin/provider-connections/${encodeURIComponent(existing.connection_id)}`
            : '/api/admin/provider-connections',
          {
            method: existing ? 'PATCH' : 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              connection_id: existing?.connection_id || option.id,
              provider_id: option.providerId,
              provider_type: option.kind,
              kind: option.kind,
              display_name: option.label,
              enabled: true,
              base_url: draft.baseUrl.trim(),
              source_role: 'execution_source',
              capability_ids: option.capabilityIds || [],
              runtime_profile_ids: option.runtimeProfileIds || [],
              config,
              metadata: { ui_source: 'vector_settings' },
              secretless: option.secretless || false,
              credential: draft.credential || undefined,
            }),
          }
        );
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(resolveUiErrorMessage(payload, copy('admin.vector_settings.save_error', '保存向量设置失败。', 'Failed to save vector settings.')));
      }
      setMessage(copy('admin.vector_settings.saved', '设置已保存。模型、维度或数据库发生变化时，请在保存后检查并重建现有索引。', 'Settings saved. If the model, dimensions, or database changed, inspect and rebuild existing indexes.'));
      await loadConnections();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : copy('admin.vector_settings.save_error', '保存向量设置失败。', 'Failed to save vector settings.'));
    } finally {
      setSavingGroup('');
    }
  }

  async function testGroup(group: VectorGroup) {
    const connection = activeConnections[group];
    if (!connection) return;
    setTestingGroup(group);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/admin/provider-connections/${encodeURIComponent(connection.connection_id)}/test`, {
        method: 'POST',
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload?.data?.ok === false) {
        throw new Error(resolveUiErrorMessage(payload, copy('admin.vector_settings.test_error', '连接测试失败。', 'Connection test failed.')));
      }
      setMessage(copy('admin.vector_settings.test_passed', '连接测试通过。', 'Connection test passed.'));
      await loadConnections();
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : copy('admin.vector_settings.test_error', '连接测试失败。', 'Connection test failed.'));
    } finally {
      setTestingGroup('');
    }
  }

  if (loading) return <AdminRouteSkeleton />;

  const groups: Array<{ id: VectorGroup; title: string; description: string }> = [
    { id: 'embedding', title: copy('admin.vector_settings.embedding_title', 'Embedding 模型', 'Embedding model'), description: copy('admin.vector_settings.embedding_desc', '选择一个向量生成服务，并固定模型与向量维度。', 'Choose one embedding service and keep its model and dimensions explicit.') },
    { id: 'store', title: copy('admin.vector_settings.store_title', '向量数据库', 'Vector database'), description: copy('admin.vector_settings.store_desc', '选择内置 PostgreSQL 或一个外部向量数据库。', 'Choose built-in PostgreSQL or one external vector database.') },
    { id: 'rerank', title: copy('admin.vector_settings.rerank_title', '结果重排', 'Result reranking'), description: copy('admin.vector_settings.rerank_desc', '可选地对向量检索结果执行第二阶段排序。', 'Optionally apply a second-stage reranker to vector-search results.') },
  ];

  const readyCount = (Object.keys(activeConnections) as VectorGroup[]).filter(
    (group) => group === 'embedding'
      ? Boolean(activeConnections.embedding?.configured)
      : !activeConnections[group] || Boolean(activeConnections[group]?.configured)
  ).length;

  return (
    <BackofficePageStack data-page-model="configuration">
      <BackofficePrimaryPanel
        eyebrow={copy('admin.vector_settings.eyebrow', '运行设置', 'Runtime settings')}
        title={copy('admin.vector_settings.title', '向量设置', 'Vector settings')}
        description={copy('admin.vector_settings.description', '配置站点知识检索使用的 Embedding、向量数据库和可选重排服务。', 'Configure the embedding, vector database, and optional reranking used by Site Knowledge search.')}
        actions={<Link href="/admin/vector-observability" className="btn btn-secondary">{copy('admin.vector_settings.open_observability', '查看向量诊断', 'Open vector diagnostics')}</Link>}
        summary={<BackofficeSummaryStrip items={[
          { label: copy('admin.vector_settings.ready_groups', '已就绪配置组', 'Ready groups'), value: `${readyCount}/3` },
          { label: copy('admin.vector_settings.selection_rule', '选择规则', 'Selection rule'), value: copy('admin.vector_settings.single_choice', '每组单选', 'One per group') },
          { label: copy('admin.vector_settings.index_rule', '索引规则', 'Index rule'), value: copy('admin.vector_settings.rebuild_required', '变更后检查重建', 'Review rebuild after change') },
        ]} />}
      >
        <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
          {copy('admin.vector_settings.boundary', '这里仅配置 Cloud 托管运行组件，不定义 WordPress 能力、工作流或写入权限。', 'This page configures Cloud runtime components only; it does not define WordPress abilities, workflows, or write authority.')}
        </p>
      </BackofficePrimaryPanel>

      {error ? <BackofficeDiagnosticNotice message={error} retryLabel={copy('common.retry', '重试', 'Retry')} onRetry={() => void loadConnections()} /> : null}
      {message ? <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">{message}</p> : null}

      {groups.map((group) => {
        const options = VECTOR_OPTIONS.filter((option) => option.group === group.id);
        const selectedOption = options.find((option) => option.id === selection[group.id]);
        const draft = drafts[group.id];
        const active = activeConnections[group.id];
        const external = Boolean(selectedOption?.kind);
        return (
          <BackofficeSectionPanel key={group.id} data-vector-group={group.id}>
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
              <div><h2 className="text-base font-semibold text-slate-950 dark:text-white">{group.title}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{group.description}</p></div>
              <BackofficeStatusBadge label={active ? (active.configured ? copy('common.ready', '已就绪', 'Ready') : copy('common.missing_config', '缺少凭据', 'Missing credential')) : selectedOption ? copy('common.builtin_or_disabled', '内置或关闭', 'Built-in or disabled') : copy('common.not_configured', '未配置', 'Not configured')} status={active?.configured ? 'success' : active ? 'warning' : 'info'} />
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              {options.map((option) => {
                const selected = selection[group.id] === option.id;
                return <button key={option.id} type="button" aria-pressed={selected} onClick={() => chooseOption(group.id, option)} className={`cursor-pointer rounded-xl border p-4 text-left transition ${selected ? 'border-blue-500 bg-blue-50/80 ring-2 ring-blue-500/15 dark:bg-blue-950/20' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700'}`}><span className="font-semibold text-slate-950 dark:text-white">{zh ? option.labelZh || option.label : option.label}</span><span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">{zh ? option.descriptionZh : option.description}</span></button>;
              })}
            </div>
            {selectedOption && external ? (
              <div className="mt-5 grid gap-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/30 md:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.vector_settings.base_url', '服务地址', 'Service URL')}<input className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.baseUrl} onChange={(event) => updateDraft(group.id, { baseUrl: event.target.value })} /></label>
                <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.vector_settings.credential', 'API Key / Token', 'API key / token')}<input type="password" autoComplete="new-password" className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.credential} onChange={(event) => updateDraft(group.id, { credential: event.target.value })} placeholder={active?.configured ? copy('admin.vector_settings.keep_credential', '留空则保留已保存凭据', 'Leave blank to keep saved credential') : ''} /></label>
                {group.id !== 'store' ? <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.vector_settings.model', '模型', 'Model')}<input className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.modelId} onChange={(event) => updateDraft(group.id, { modelId: event.target.value })} /></label> : null}
                {group.id === 'embedding' ? <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.vector_settings.dimensions', '向量维度', 'Vector dimensions')}<input type="number" min={1} className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.dimensions} onChange={(event) => updateDraft(group.id, { dimensions: event.target.value })} /></label> : null}
                {group.id === 'store' ? <><label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">{copy('admin.vector_settings.database', '数据库', 'Database')}<input className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.database} onChange={(event) => updateDraft(group.id, { database: event.target.value })} /></label><label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">Collection<input className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.collection} onChange={(event) => updateDraft(group.id, { collection: event.target.value })} /></label></> : null}
                {group.id === 'rerank' ? <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">Top K<input type="number" min={1} className="h-11 rounded-lg border border-slate-300 bg-white px-3 dark:border-slate-700 dark:bg-slate-950" value={draft.topK} onChange={(event) => updateDraft(group.id, { topK: event.target.value })} /></label> : null}
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">{copy('admin.vector_settings.reindex_warning', '修改模型、维度或数据库后，现有索引可能需要重建。', 'Changing the model, dimensions, or database may require rebuilding existing indexes.')}</p>
              <div className="flex gap-2">{active && external ? <button type="button" className="btn btn-secondary btn-sm" disabled={testingGroup === group.id || savingGroup !== ''} onClick={() => void testGroup(group.id)}>{testingGroup === group.id ? copy('common.testing', '测试中…', 'Testing…') : copy('common.test_connection', '测试连接', 'Test connection')}</button> : null}<button type="button" className="btn btn-primary btn-sm" disabled={savingGroup !== '' || testingGroup !== ''} onClick={() => void saveGroup(group.id)}>{savingGroup === group.id ? copy('common.saving', '保存中…', 'Saving…') : copy('common.save', '保存', 'Save')}</button></div>
            </div>
          </BackofficeSectionPanel>
        );
      })}
    </BackofficePageStack>
  );
}
