import { humanizeStatusToken, normalizeStatusToken, translateStatusLabel } from './status-display';

type TranslateFn = (key: string, vars?: Record<string, string>, fallback?: string) => string;

const ADMIN_AUDIT_EVENT_LABELS: Record<string, string> = {
  'site_admin_access.upsert': 'audit.kind.site_admin_access.upsert',
  'portal_magic_link.requested': 'audit.kind.portal_login_code.requested',
  'portal_magic_link.consumed': 'audit.kind.portal_login_code.verified',
  'api_key.created': 'audit.kind.api_key.created',
  'api_key.rotated': 'audit.kind.api_key.rotated',
  'api_key.revoked': 'audit.kind.api_key.revoked',
  'site.connected': 'audit.kind.site.connected',
  'site.disconnected': 'audit.kind.site.disconnected',
  'subscription.activated': 'audit.kind.subscription.activated',
  'subscription.updated': 'audit.kind.subscription.updated',
  'subscription.canceled': 'audit.kind.subscription.canceled',
};

const ADMIN_ROLE_LABELS: Record<string, string> = {
  site_admin: 'admin.external_role_site_admin',
  platform_admin: 'admin.external_role_platform_admin',
};

const ADMIN_REASON_LABELS: Record<string, string> = {
  support_debug: 'admin.reason_support_debug',
  ended_from_admin_console: 'admin.reason_ended_from_admin_console',
  ended_from_admin_global_bar: 'admin.reason_ended_from_admin_global_bar',
  ended_from_platform_admins: 'admin.reason_ended_from_platform_admins',
  ended_from_account_detail: 'admin.reason_ended_from_account_detail',
  ended_from_site_detail: 'admin.reason_ended_from_site_detail',
};

const ADMIN_ALLOWED_ACTION_LABELS: Record<string, string> = {
  view_sites: 'admin.allowed_action_view_sites',
  view_usage: 'admin.allowed_action_view_usage',
  view_billing: 'admin.allowed_action_view_billing',
  view_audit: 'admin.allowed_action_view_audit',
  provision_sites: 'admin.allowed_action_provision_sites',
  remove_sites: 'admin.allowed_action_remove_sites',
};

function humanizeCode(value: string) {
  return value
    .replace(/[._]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function translateAdminAuditEventKind(eventKind: string, t: TranslateFn) {
  const key = ADMIN_AUDIT_EVENT_LABELS[eventKind];
  if (key) {
    return t(key);
  }
  return humanizeCode(eventKind);
}

export function translateAdminRole(role: string, t: TranslateFn) {
  const key = ADMIN_ROLE_LABELS[role];
  if (key) {
    return t(key);
  }
  return humanizeCode(role);
}

export function translateExternalCommercialRole(role: string, t: TranslateFn) {
  const normalizedRole = String(role || '').trim();
  if (normalizedRole === 'platform_admin') {
    return t('admin.external_role_platform_admin', {}, 'Platform Admin');
  }
  return t('admin.external_role_site_admin', {}, 'Site Admin');
}

export function translateAdminReasonCode(reasonCode: string, t: TranslateFn) {
  const key = ADMIN_REASON_LABELS[reasonCode];
  if (key) {
    return t(key);
  }
  return humanizeCode(reasonCode);
}

export function translateAllowedAction(action: string, t: TranslateFn) {
  const key = ADMIN_ALLOWED_ACTION_LABELS[action];
  if (key) {
    return t(key);
  }
  return humanizeCode(action);
}

export function translateAdminOutcome(outcome: string, t: TranslateFn) {
  if (normalizeStatusToken(outcome) === 'error') {
    return t('common.error');
  }
  return translateStatusLabel(outcome, t, humanizeStatusToken(outcome));
}
