'use client';

import {
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { useLocale } from '@/contexts/LocaleContext';

export type CloudWorkflowMetadata = {
  workflowId: string;
  workflowVersion: string;
  title: string;
  summary: string;
  abilityName: string;
  contract: string;
  owner: string;
  handoffOwner: string;
  executionPattern: string;
  storageMode: string;
  badges: Array<{ label: string; status: string }>;
  steps: string[];
  stopConditions: string[];
  directWordPressWrite: boolean;
  requiresOperatorReview: boolean;
  failClosedBehavior: string;
};

export function normalizeCloudWorkflowMetadata(raw: any): CloudWorkflowMetadata {
  return {
    workflowId: String(raw?.workflow_id ?? ''),
    workflowVersion: String(raw?.workflow_version ?? ''),
    title: String(raw?.title ?? ''),
    summary: String(raw?.summary ?? ''),
    abilityName: String(raw?.ability_name ?? ''),
    contract: String(raw?.contract ?? ''),
    owner: String(raw?.owner ?? ''),
    handoffOwner: String(raw?.handoff_owner ?? ''),
    executionPattern: String(raw?.execution_pattern ?? ''),
    storageMode: String(raw?.storage_mode ?? ''),
    badges: Array.isArray(raw?.badges)
      ? raw.badges.map((badge: any) => ({
          label: String(badge?.label ?? ''),
          status: String(badge?.status ?? 'inactive'),
        })).filter((badge: { label: string }) => badge.label)
      : [],
    steps: Array.isArray(raw?.steps) ? raw.steps.map(String).filter(Boolean) : [],
    stopConditions: Array.isArray(raw?.stop_conditions)
      ? raw.stop_conditions.map(String).filter(Boolean)
      : [],
    directWordPressWrite: Boolean(raw?.direct_wordpress_write),
    requiresOperatorReview: Boolean(raw?.requires_operator_review),
    failClosedBehavior: String(raw?.fail_closed_behavior ?? ''),
  };
}

type CloudWorkflowMetadataPanelProps = {
  metadata: CloudWorkflowMetadata;
  className?: string;
};

export function CloudWorkflowMetadataPanel({
  metadata,
  className,
}: CloudWorkflowMetadataPanelProps) {
  const { t } = useLocale();

  if (!metadata.workflowId) {
    return null;
  }

  const badges = metadata.badges.length
    ? metadata.badges
    : [
        {
          label: metadata.directWordPressWrite
            ? t('workflow_metadata.badge_write_allowed', {}, 'write allowed')
            : t('workflow_metadata.badge_write_blocked', {}, 'write blocked'),
          status: metadata.directWordPressWrite ? 'error' : 'success',
        },
        {
          label: metadata.requiresOperatorReview
            ? t('workflow_metadata.badge_review_required', {}, 'review required')
            : t('workflow_metadata.badge_review_optional', {}, 'review optional'),
          status: metadata.requiresOperatorReview ? 'warning' : 'inactive',
        },
      ];
  const writePosture = metadata.directWordPressWrite
    ? t('workflow_metadata.write_allowed', {}, 'WordPress write allowed')
    : t('workflow_metadata.write_blocked', {}, 'WordPress write blocked');
  const reviewPosture = metadata.requiresOperatorReview
    ? t('workflow_metadata.operator_review_required', {}, 'Operator review required')
    : t('workflow_metadata.operator_review_optional', {}, 'Operator review optional');
  const handoffOwner = translateMetadataValue(t, 'handoff_owner', metadata.handoffOwner || metadata.owner || 'cloud_runtime');

  return (
    <BackofficeSectionPanel className={`space-y-5 ${className || ''}`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t('workflow_metadata.label', {}, 'Workflow metadata')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {translateWorkflowField(t, metadata.workflowId, 'title', metadata.title || metadata.workflowId)}
          </h2>
          {metadata.summary ? (
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {translateWorkflowField(t, metadata.workflowId, 'summary', metadata.summary)}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {badges.map((badge) => (
            <BackofficeStatusBadge
              key={`${badge.label}:${badge.status}`}
              label={translateMetadataValue(t, 'badge', badge.label)}
              status={badge.status}
            />
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetadataCard label={t('workflow_metadata.write_posture', {}, 'Write posture')} value={writePosture} />
        <MetadataCard label={t('workflow_metadata.review_posture', {}, 'Review posture')} value={reviewPosture} />
        <MetadataCard label={t('workflow_metadata.handoff', {}, 'Handoff')} value={handoffOwner} />
        <MetadataCard
          label={t('workflow_metadata.fail_closed', {}, 'Fail closed')}
          value={
            metadata.failClosedBehavior
              ? translateMetadataValue(t, 'fail_closed_behavior', metadata.failClosedBehavior)
              : t('workflow_metadata.not_declared', {}, 'Not declared')
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <MetadataList
          title={t('workflow_metadata.steps', {}, 'Steps')}
          items={metadata.steps.map((item) => translateMetadataValue(t, 'step', item))}
          emptyLabel={t('workflow_metadata.no_metadata', {}, 'No metadata declared.')}
        />
        <MetadataList
          title={t('workflow_metadata.stop_conditions', {}, 'Stop conditions')}
          items={metadata.stopConditions.map((item) => translateMetadataValue(t, 'stop_condition', item))}
          emptyLabel={t('workflow_metadata.no_metadata', {}, 'No metadata declared.')}
        />
      </div>

      <details className="rounded-2xl border border-slate-200/80 bg-white/70 p-4 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-300">
        <summary className="cursor-pointer font-semibold text-slate-700 dark:text-slate-200">
          {t('workflow_metadata.technical_metadata', {}, 'Technical metadata')}
        </summary>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <MetadataCard label={t('workflow_metadata.workflow', {}, 'Workflow')} value={metadata.workflowId} />
          <MetadataCard label={t('workflow_metadata.version', {}, 'Version')} value={metadata.workflowVersion} />
          <MetadataCard
            label={metadata.abilityName ? t('workflow_metadata.ability', {}, 'Ability') : t('workflow_metadata.contract', {}, 'Contract')}
            value={metadata.abilityName || metadata.contract}
          />
          <MetadataCard
            label={t('workflow_metadata.pattern', {}, 'Pattern')}
            value={translateMetadataValue(t, 'execution_pattern', metadata.executionPattern)}
          />
          <MetadataCard
            label={t('workflow_metadata.storage', {}, 'Storage')}
            value={translateMetadataValue(t, 'storage_mode', metadata.storageMode)}
          />
        </div>
      </details>
    </BackofficeSectionPanel>
  );
}

function MetadataCard({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <BackofficeStackCard className={className}>
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold text-slate-800 dark:text-slate-100">
        {value || '-'}
      </p>
    </BackofficeStackCard>
  );
}

function MetadataList({
  title,
  items,
  emptyLabel,
}: {
  title: string;
  items: string[];
  emptyLabel: string;
}) {
  return (
    <BackofficeStackCard>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
        {title}
      </p>
      <div className="mt-3 space-y-2">
        {items.length ? (
          items.map((item) => (
            <p key={item} className="text-sm leading-6 text-slate-700 dark:text-slate-200">
              {item}
            </p>
          ))
        ) : (
          <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
            {emptyLabel}
          </p>
        )}
      </div>
    </BackofficeStackCard>
  );
}

function metadataKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function translateWorkflowField(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  workflowId: string,
  field: 'title' | 'summary',
  fallback: string
): string {
  return t(`workflow_metadata.workflow.${metadataKey(workflowId)}.${field}`, {}, fallback);
}

function translateMetadataValue(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  group: string,
  value: string
): string {
  return t(`workflow_metadata.${group}.${metadataKey(value)}`, {}, value);
}
