'use client';

import {
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';

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
  if (!metadata.workflowId) {
    return null;
  }

  const badges = metadata.badges.length
    ? metadata.badges
    : [
        {
          label: metadata.directWordPressWrite ? 'write allowed' : 'write blocked',
          status: metadata.directWordPressWrite ? 'error' : 'success',
        },
        {
          label: metadata.requiresOperatorReview ? 'review required' : 'review optional',
          status: metadata.requiresOperatorReview ? 'warning' : 'inactive',
        },
      ];

  return (
    <BackofficeSectionPanel className={`space-y-5 ${className || ''}`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            Workflow metadata
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {metadata.title || metadata.workflowId}
          </h2>
          {metadata.summary ? (
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {metadata.summary}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {badges.map((badge) => (
            <BackofficeStatusBadge
              key={`${badge.label}:${badge.status}`}
              label={badge.label}
              status={badge.status}
            />
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetadataCard label="Workflow" value={metadata.workflowId} />
        <MetadataCard label="Version" value={metadata.workflowVersion} />
        <MetadataCard label={metadata.abilityName ? 'Ability' : 'Contract'} value={metadata.abilityName || metadata.contract} />
        <MetadataCard label="Handoff" value={metadata.handoffOwner || metadata.owner} />
        <MetadataCard label="Pattern" value={metadata.executionPattern} />
        <MetadataCard label="Storage" value={metadata.storageMode} />
        <MetadataCard label="Fail closed" value={metadata.failClosedBehavior} className="md:col-span-2" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <MetadataList title="Steps" items={metadata.steps} />
        <MetadataList title="Stop conditions" items={metadata.stopConditions} />
      </div>
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
      <p className="mt-1 font-mono text-xs text-slate-700 dark:text-slate-200">
        {value || '-'}
      </p>
    </BackofficeStackCard>
  );
}

function MetadataList({ title, items }: { title: string; items: string[] }) {
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
            No metadata declared.
          </p>
        )}
      </div>
    </BackofficeStackCard>
  );
}
