'use client';

import Link from 'next/link';
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

type RelatedEntry = Omit<AdvancedEntry, 'groupKey' | 'groupFallback'>;

const advancedEntries: AdvancedEntry[] = [
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
    href: '/admin/hosted-models',
    titleKey: 'admin.nav_hosted_models',
    titleFallback: 'Hosted Models',
    descKey: 'admin.advanced.hosted_models_desc',
    descFallback: 'Hosted model governance, metering coverage, provider calls, and model risk.',
    actionKey: 'admin.advanced.action_view_model_gaps',
    actionFallback: 'View model gaps',
    groupKey: 'admin.advanced.group_governance',
    groupFallback: 'Governance',
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
  {
    href: '/admin/audio-workbench',
    titleKey: 'admin.nav_audio_workbench',
    titleFallback: 'Audio Workbench',
    descKey: 'admin.advanced.audio_workbench_desc',
    descFallback: 'Article narration and long-form audio summary job creation.',
    actionKey: 'admin.advanced.action_open_audio_workbench',
    actionFallback: 'Open audio workbench',
    groupKey: 'admin.advanced.group_capabilities',
    groupFallback: 'Capabilities',
  },
];

const relatedEntries: RelatedEntry[] = [
  {
    href: '/admin/ai-resources',
    titleKey: 'admin.nav_ai_resources',
    titleFallback: 'Provider Management',
    descKey: 'admin.advanced.ai_resources_related_desc',
    descFallback:
      'Top-level model and capability supplier operations. Open it from here when provider configuration needs attention.',
    actionKey: 'admin.advanced.action_open_ai_resources',
    actionFallback: 'Open provider management',
  },
];

export default function AdminTroubleshootingPage() {
  const { t } = useLocale();
  const groups = Array.from(new Set(advancedEntries.map((entry) => entry.groupKey)));

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.advanced.title', {}, 'Advanced Troubleshooting')}
        description={t(
          'admin.advanced.desc',
          {},
          'Low-frequency diagnostics live here so the primary admin path stays focused on customers, packages, and support decisions.'
        )}
        aside={(
          <div className="w-full xl:w-[34rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.advanced.groups', {}, 'Groups'), value: groups.length, size: 'compact' },
                { label: t('admin.advanced.entries', {}, 'Entries'), value: advancedEntries.length, size: 'compact' },
                { label: t('admin.visibility_advanced', {}, 'Advanced'), value: t('common.enabled', {}, 'Enabled'), size: 'compact' },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            />
          </div>
        )}
      />

      {groups.map((groupKey) => {
        const groupEntries = advancedEntries.filter((entry) => entry.groupKey === groupKey);
        const groupFallback = groupEntries[0]?.groupFallback || 'Advanced';

        return (
          <BackofficeSectionPanel key={groupKey} className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.visibility_advanced', {}, 'Advanced')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t(groupKey, {}, groupFallback)}
              </h2>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {groupEntries.map((entry) => (
                <BackofficeStackCard key={entry.href} className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-slate-950 dark:text-white">
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
          </BackofficeSectionPanel>
        );
      })}

      <BackofficeSectionPanel className="space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('admin.advanced.related', {}, 'Related operations')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('admin.advanced.related_ai_operations', {}, 'AI operations')}
          </h2>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {relatedEntries.map((entry) => (
            <BackofficeStackCard key={entry.href} className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-slate-950 dark:text-white">
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
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}
