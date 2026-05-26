'use client';

import React from 'react';
import { BackofficeTag, type BackofficeTagTone } from '@/components/backoffice/BackofficeTag';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

function toneForStatus(value: string): BackofficeTagTone {
  switch (value) {
    case 'candidate':
    case 'reviewed':
      return 'info';
    case 'suppressed':
      return 'danger';
    case 'pending':
      return 'warning';
    default:
      return 'neutral';
  }
}

export function translateReviewStatus(value: string, t: TranslateFn): string {
  switch (value) {
    case 'pending':
      return t('admin.review_status_pending', {}, 'Pending');
    case 'reviewed':
      return t('admin.review_status_reviewed', {}, 'Reviewed');
    case 'candidate':
      return t('admin.review_status_candidate', {}, 'Candidate');
    case 'suppressed':
      return t('admin.review_status_suppressed', {}, 'Suppressed');
    default:
      return value || t('admin.review_status_pending', {}, 'Pending');
  }
}

export function ReviewStatusBadge({
  status,
  t,
}: {
  status: string;
  t: TranslateFn;
}) {
  return (
    <BackofficeTag tone={toneForStatus(status)} dataUi="review-status-badge">
      {translateReviewStatus(status, t)}
    </BackofficeTag>
  );
}
