'use client';

import React from 'react';
import {
  BackofficeTag,
  backofficeTagToneClassName,
  type BackofficeTagTone,
} from '@/components/backoffice/BackofficeTag';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export type AdminTagTone = BackofficeTagTone;

export function adminTagToneClassName(tone: AdminTagTone): string {
  return backofficeTagToneClassName(tone);
}

function badgeTone(value: string): AdminTagTone {
  switch (value) {
    case 'default':
      return 'success';
    case 'advanced':
    case 'balanced':
      return 'info';
    case 'budget':
      return 'warning';
    case 'premium':
    case 'hidden':
      return 'accent';
    default:
      return 'neutral';
  }
}

export function AdminSemanticBadge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: AdminTagTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <BackofficeTag tone={tone} className={className} dataUi="admin-semantic-badge">
      {children}
    </BackofficeTag>
  );
}

export function translateVisibility(value: string, t: TranslateFn): string {
  switch (value) {
    case 'default':
      return t('admin.visibility_default', {}, 'Default');
    case 'advanced':
      return t('admin.visibility_advanced', {}, 'Advanced');
    case 'hidden':
      return t('admin.visibility_hidden', {}, 'Hidden');
    default:
      return value || t('admin.visibility_default', {}, 'Default');
  }
}

export function translateCostTier(value: string, t: TranslateFn): string {
  switch (value) {
    case 'budget':
      return t('admin.cost_tier_budget', {}, 'Budget');
    case 'balanced':
      return t('admin.cost_tier_balanced', {}, 'Balanced');
    case 'premium':
      return t('admin.cost_tier_premium', {}, 'Premium');
    default:
      return value;
  }
}

export function HostedMetadataBadges({
  metadata,
  t,
}: {
  metadata: {
    recommended?: boolean;
    cost_tier?: string;
    visibility?: string;
    badges?: string[];
  };
  t: TranslateFn;
}) {
  return (
    <>
      <AdminSemanticBadge tone={badgeTone(metadata.visibility || 'default')}>
        {translateVisibility(metadata.visibility || 'default', t)}
      </AdminSemanticBadge>
      {metadata.recommended ? (
        <AdminSemanticBadge tone="success">
          {t('admin.recommended', {}, 'Recommended')}
        </AdminSemanticBadge>
      ) : null}
      {metadata.cost_tier ? (
        <AdminSemanticBadge tone={badgeTone(metadata.cost_tier)}>
          {translateCostTier(metadata.cost_tier, t)}
        </AdminSemanticBadge>
      ) : null}
      {(metadata.badges || []).map((badge) => (
        <AdminSemanticBadge key={badge} tone="neutral">
          {badge}
        </AdminSemanticBadge>
      ))}
    </>
  );
}
