import { localizePackageAlias } from './admin-plan-copy';
import { localizeTopUpPackLabel } from './topup-pack-copy';

type TranslateFn = (key: string, vars?: Record<string, string>, fallback?: string) => string;

type RequestLike = {
  request_type?: string;
  status?: string;
  payload?: Record<string, unknown>;
};

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  return String(value);
}

export function formatPortalActionRequestTypeLabel(t: TranslateFn, requestType?: string): string {
  switch (String(requestType || '').trim()) {
    case 'package_change':
      return t('admin.request_type_package_change', {}, 'Package change');
    case 'topup_pack':
      return t('admin.request_type_topup_pack', {}, 'Top-up pack');
    case 'site_delete':
      return t('admin.request_type_site_delete', {}, 'Site delete');
    case 'usage_alert':
      return t('admin.request_type_usage_alert', {}, 'Usage alert');
    case 'key_expiry':
      return t('admin.request_type_key_expiry', {}, 'Key expiry');
    case 'auth_guard':
      return t('admin.request_type_auth_guard', {}, 'Auth guard');
    case 'compliance_export':
      return t('compliance.request_export', {}, 'Request Data Export');
    case 'compliance_deletion_review':
      return t('compliance.request_deletion', {}, 'Request Deletion Review');
    case 'compliance_report':
      return t('compliance.request_report', {}, 'Request Compliance Report');
    default:
      return stringifyValue(requestType) || t('common.not_found', {}, 'Not found');
  }
}

export function formatPortalActionRequestStatusLabel(t: TranslateFn, status?: string): string {
  switch (String(status || '').trim()) {
    case 'open':
      return t('admin.request_status_open', {}, 'Open');
    case 'acknowledged':
      return t('admin.request_status_acknowledged', {}, 'Acknowledged');
    case 'resolved':
      return t('admin.request_status_resolved', {}, 'Resolved');
    case 'canceled':
      return t('admin.request_status_canceled', {}, 'Canceled');
    default:
      return stringifyValue(status) || t('common.not_found', {}, 'Not found');
  }
}

export function formatPortalActionRequestResultSummary(
  t: TranslateFn,
  item: RequestLike
): string | null {
  const payload = item.payload || {};
  const result = (payload.application_result || {}) as Record<string, unknown>;
  const resultKind = stringifyValue(result.kind);

  if (resultKind === 'package_changed') {
    const targetPackage = stringifyValue(result.target_package);
    const tierId =
      stringifyValue(
        ((result.subscription || {}) as Record<string, unknown>).metadata
          ? (((result.subscription || {}) as Record<string, unknown>).metadata as Record<string, unknown>).tier_id
          : ''
      ) || (targetPackage === 'bulk' ? 'agency' : targetPackage === 'free' ? 'starter' : 'pro');
    const packageLabel = localizePackageAlias(
      t,
      tierId,
      targetPackage === 'bulk' ? 'Bulk' : targetPackage === 'free' ? 'Free' : 'Basic'
    );
    return t(
      'admin.request_result_package_changed',
      { package: packageLabel },
      `Package changed to ${packageLabel}`
    );
  }

  if (resultKind === 'topup_applied') {
    const packLabel = localizeTopUpPackLabel(
      t,
      stringifyValue(result.pack_id),
      stringifyValue(result.pack_label)
    );
    return t(
      'admin.request_result_topup_applied',
      { pack: packLabel || t('admin.request_type_topup_pack', {}, 'Top-up pack') },
      `Applied ${packLabel || 'top-up pack'}`
    );
  }

  if (String(item.request_type || '') === 'site_delete' && String(item.status || '') === 'open') {
    return t(
      'admin.request_result_site_delete_pending',
      {},
      'Site delete or disconnect request is waiting for operator review.'
    );
  }

  if (String(item.request_type || '') === 'site_delete' && String(item.status || '') === 'resolved') {
    return t(
      'admin.request_result_site_delete_resolved',
      {},
      'Site delete or disconnect request has been processed.'
    );
  }

  const decision = stringifyValue(payload.admin_decision);
  const decisionNote = stringifyValue(payload.admin_decision_note);
  if (decision === 'reject') {
    if (decisionNote) {
      return t(
        'admin.request_result_rejected_with_note',
        { note: decisionNote },
        `Rejected: ${decisionNote}`
      );
    }
    return t('admin.request_result_rejected', {}, 'Rejected');
  }

  if (decision === 'approve') {
    if (decisionNote) {
      return t(
        'admin.request_result_approved_with_note',
        { note: decisionNote },
        `Approved: ${decisionNote}`
      );
    }
    return t('admin.request_result_approved', {}, 'Approved');
  }

  if (String(item.status || '') === 'resolved') {
    return t('admin.request_result_resolved_generic', {}, 'Processed');
  }

  return null;
}
