'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';

type AdvancedEntry = {
  href: string;
  titleKey: string;
  titleFallback: string;
  descKey: string;
  descFallback: string;
  actionKey: string;
  actionFallback: string;
  groupKey: string;
  groupFallback: string;
};

type AdvancedGroup = {
  key: string;
  fallback: string;
  descKey: string;
  descFallback: string;
};

const advancedEntries: AdvancedEntry[] = [
  {
    href: '#runtime-evidence',
    titleKey: 'admin.advanced.runtime_evidence_title',
    titleFallback: 'Runtime Resource Evidence',
    descKey: 'admin.advanced.runtime_evidence_desc',
    descFallback: 'Runtime resolution, capability matrix, runtime configurations, and recent runtime evidence.',
    actionKey: 'admin.advanced.action_view_runtime_evidence',
    actionFallback: 'View runtime evidence',
    groupKey: 'admin.advanced.group_runtime',
    groupFallback: 'Runtime evidence',
  },
  {
    href: '/admin/plugin-observability',
    titleKey: 'admin.nav_plugin_observability',
    titleFallback: 'Plugin Observability',
    descKey: 'admin.advanced.plugin_observability_desc',
    descFallback: 'Plugin event volume, error pressure, latency, and recent failure evidence.',
    actionKey: 'admin.advanced.action_view_plugin_observability',
    actionFallback: 'View plugin evidence',
    groupKey: 'admin.advanced.group_runtime',
    groupFallback: 'Runtime evidence',
  },
  {
    href: '/admin/media-observability',
    titleKey: 'admin.nav_media_observability',
    titleFallback: 'Media Observability',
    descKey: 'admin.advanced.media_observability_desc',
    descFallback: 'Media processing jobs, failures, processing duration, and compression value.',
    actionKey: 'admin.advanced.action_view_media_jobs',
    actionFallback: 'View media jobs',
    groupKey: 'admin.advanced.group_runtime',
    groupFallback: 'Runtime evidence',
  },
  {
    href: '/admin/agent-feedback',
    titleKey: 'admin.nav_agent_feedback',
    titleFallback: 'Agent Feedback Quality',
    descKey: 'admin.advanced.agent_feedback_desc',
    descFallback: 'Read-only quality signals from local operator feedback across Cloud-backed AI assistance.',
    actionKey: 'admin.advanced.action_view_agent_feedback',
    actionFallback: 'View quality feedback',
    groupKey: 'admin.advanced.group_runtime',
    groupFallback: 'Runtime evidence',
  },
  {
    href: '/admin/vector-observability',
    titleKey: 'admin.nav_vector_observability',
    titleFallback: 'Vector Observability',
    descKey: 'admin.advanced.vector_observability_desc',
    descFallback: 'Vector and site-knowledge indexing health for support investigations.',
    actionKey: 'admin.advanced.action_view_vector_health',
    actionFallback: 'View vector health',
    groupKey: 'admin.advanced.group_runtime',
    groupFallback: 'Runtime evidence',
  },
  {
    href: '/admin/ai-advisor',
    titleKey: 'admin.nav_ai_advisor',
    titleFallback: 'AI Advisor',
    descKey: 'admin.advanced.ai_advisor_desc',
    descFallback: 'AI-assisted diagnosis for selected operational signals.',
    actionKey: 'admin.advanced.action_open_advisor',
    actionFallback: 'Open advisor',
    groupKey: 'admin.advanced.group_governance',
    groupFallback: 'Governance',
  },
];

const advancedGroups: AdvancedGroup[] = [
  {
    key: 'admin.advanced.group_runtime',
    fallback: 'Runtime evidence',
    descKey: 'admin.advanced.group_runtime_desc',
    descFallback: 'Read current runtime evidence before opening individual plugin, media, vector, or feedback detail.',
  },
  {
    key: 'admin.advanced.group_governance',
    fallback: 'Governance',
    descKey: 'admin.advanced.group_governance_desc',
    descFallback: 'Use advisory diagnostics to explain operational posture without changing approval, routing, or WordPress state.',
  },
];

const runtimeEvidenceItems = [
  {
    titleKey: 'admin.advanced.runtime_resolution_title',
    titleFallback: 'Runtime resolution',
    descKey: 'admin.advanced.runtime_resolution_desc',
    descFallback: 'Capability to profile, supplier, and model selection evidence. Read-only, not a router editor.',
  },
  {
    titleKey: 'admin.advanced.capability_matrix_title',
    titleFallback: 'Capability matrix',
    descKey: 'admin.advanced.capability_matrix_desc',
    descFallback: 'Current Cloud runtime mapping across capabilities, selected providers, and write posture.',
  },
  {
    titleKey: 'admin.advanced.runtime_profiles_title',
    titleFallback: 'Runtime configurations',
    descKey: 'admin.advanced.runtime_profiles_desc',
    descFallback: 'Cloud runtime profile metadata and selected provider/model references.',
  },
  {
    titleKey: 'admin.advanced.recent_runtime_evidence_title',
    titleFallback: 'Recent runtime evidence',
    descKey: 'admin.advanced.recent_runtime_evidence_desc',
    descFallback: 'Recent run metadata used for diagnostics without exposing prompts, results, or provider secrets.',
  },
];

export default function AdminTroubleshootingPage() {
  const { t } = useLocale();
  const [activeGroupKey, setActiveGroupKey] = useState<string>('all');
  const visibleEntries = useMemo(
    () => activeGroupKey === 'all'
      ? advancedEntries
      : advancedEntries.filter((entry) => entry.groupKey === activeGroupKey),
    [activeGroupKey]
  );
  const selectedGroup = activeGroupKey === 'all'
    ? null
    : advancedGroups.find((group) => group.key === activeGroupKey) || null;
  const focusEntry = visibleEntries[0] || advancedEntries[0];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.advanced.title', {}, 'Advanced Troubleshooting')}
        description={t(
          'admin.advanced.desc',
          {},
          'Use this read-only catalog when routine customer, package, or resource views are not enough to explain an operational signal.'
        )}
        aside={(
          <div className="w-full xl:w-[34rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.advanced.groups', {}, 'Groups'), value: advancedGroups.length, size: 'compact' },
                { label: t('admin.advanced.entries', {}, 'Entries'), value: advancedEntries.length, size: 'compact' },
                {
                  label: t('admin.advanced.mode', {}, 'Mode'),
                  value: t('admin.advanced.read_only', {}, 'Read-only'),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            />
          </div>
        )}
      />

      <BackofficeSectionPanel className="grid gap-5 xl:grid-cols-[18rem_minmax(0,1fr)_22rem]">
        <div className="space-y-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.advanced.catalog_eyebrow', {}, 'Diagnostic lanes')}
            </p>
            <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
              {t('admin.advanced.catalog_title', {}, 'Choose an evidence lane')}
            </h2>
          </div>
          <div className="space-y-2" role="tablist" aria-label={t('admin.advanced.group_filter_label', {}, 'Diagnostic group')}>
            <button
              type="button"
              role="tab"
              aria-selected={activeGroupKey === 'all'}
              className={`w-full rounded-[1rem] border px-4 py-3 text-left text-sm transition ${
                activeGroupKey === 'all'
                  ? 'border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-800 dark:bg-blue-950/35 dark:text-blue-100'
                  : 'border-slate-200 bg-white/70 text-slate-600 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300'
              }`}
              onClick={() => setActiveGroupKey('all')}
            >
              <span className="block font-semibold">{t('admin.advanced.all_groups', {}, 'All diagnostics')}</span>
              <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t('admin.advanced.all_groups_desc', {}, 'Scan every low-frequency evidence source in one pass.')}
              </span>
            </button>
            {advancedGroups.map((group) => {
              const count = advancedEntries.filter((entry) => entry.groupKey === group.key).length;
              return (
                <button
                  key={group.key}
                  type="button"
                  role="tab"
                  aria-selected={activeGroupKey === group.key}
                  className={`w-full rounded-[1rem] border px-4 py-3 text-left text-sm transition ${
                    activeGroupKey === group.key
                      ? 'border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-800 dark:bg-blue-950/35 dark:text-blue-100'
                      : 'border-slate-200 bg-white/70 text-slate-600 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300'
                  }`}
                  onClick={() => setActiveGroupKey(group.key)}
                >
                  <span className="flex items-center justify-between gap-3 font-semibold">
                    <span>{t(group.key, {}, group.fallback)}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                      {count}
                    </span>
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t(group.descKey, {}, group.descFallback)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.visibility_advanced', {}, 'Advanced')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {selectedGroup
                  ? t(selectedGroup.key, {}, selectedGroup.fallback)
                  : t('admin.advanced.all_groups', {}, 'All diagnostics')}
              </h2>
            </div>
            <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
              {t('admin.advanced.visible_entries', { count: String(visibleEntries.length) }, '{{count}} entries')}
            </span>
          </div>

          <div className="space-y-3">
            {visibleEntries.map((entry) => (
              <BackofficeStackCard key={entry.href} className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {t(entry.groupKey, {}, entry.groupFallback)}
                  </p>
                  <h3 className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
                    {t(entry.titleKey, {}, entry.titleFallback)}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {t(entry.descKey, {}, entry.descFallback)}
                  </p>
                </div>
                <Link href={entry.href} className="btn btn-secondary shrink-0">
                  {t(entry.actionKey, {}, entry.actionFallback)}
                </Link>
              </BackofficeStackCard>
            ))}
          </div>
        </div>

        <BackofficeStackCard className="h-fit space-y-4 bg-white/80 dark:bg-slate-950/55">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.advanced.inspector_eyebrow', {}, 'Current focus')}
            </p>
            <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
              {t('admin.advanced.inspector_title', {}, 'Read-only diagnostic catalog')}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {selectedGroup
                ? t(selectedGroup.descKey, {}, selectedGroup.descFallback)
                : t('admin.advanced.inspector_desc', {}, 'Start with the lane that matches the support question, then open the narrowest evidence detail page.')}
            </p>
          </div>
          <div className="rounded-[1rem] border border-slate-200 bg-slate-50/75 p-4 dark:border-slate-800 dark:bg-slate-900/35">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              {t('admin.advanced.suggested_first_step', {}, 'Suggested first step')}
            </p>
            <h3 className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">
              {t(focusEntry.titleKey, {}, focusEntry.titleFallback)}
            </h3>
            <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t(focusEntry.descKey, {}, focusEntry.descFallback)}
            </p>
          </div>
          <p className="rounded-[1rem] border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-100">
            {t(
              'admin.advanced.boundary_note',
              {},
              'This catalog only opens read-only Cloud evidence. It does not edit provider settings, local abilities, workflow metadata, routing, prompts, billing, or WordPress content.'
            )}
          </p>
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      <div id="runtime-evidence">
      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.advanced.runtime_evidence_eyebrow', {}, 'Runtime plane')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.advanced.runtime_evidence_title', {}, 'Runtime Resource Evidence')}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'admin.advanced.runtime_evidence_scope',
                {},
                'These entries belong with runtime diagnostics, not supplier setup. They explain current Cloud execution metadata and do not edit providers, model binding, routing, prompts, abilities, or WordPress writes.'
              )}
            </p>
          </div>
          <Link href="/admin/ability-models" className="btn btn-secondary shrink-0">
            {t('admin.advanced.action_open_model_binding', {}, 'Open model binding')}
          </Link>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {runtimeEvidenceItems.map((item) => (
            <BackofficeStackCard key={item.titleKey} className="space-y-2">
              <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                {t(item.titleKey, {}, item.titleFallback)}
              </h3>
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t(item.descKey, {}, item.descFallback)}
              </p>
            </BackofficeStackCard>
          ))}
        </div>
        <p className="rounded-[1rem] border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:bg-slate-900/35 dark:text-slate-400">
          {t(
            'admin.advanced.runtime_evidence_boundary',
            {},
            'Evidence source remains Cloud runtime metadata such as run records, provider-call records, usage meter events, runtime profiles, and capability projection rows.'
          )}
        </p>
      </BackofficeSectionPanel>
      </div>

    </BackofficePageStack>
  );
}
