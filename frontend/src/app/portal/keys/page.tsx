'use client';

import Link from 'next/link';
import React, { useCallback, useEffect, useState, Suspense } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { Modal } from '@/components/ui/Modal';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import { portalClient, type PortalSiteDiagnostics, type PortalSiteSummaryRecord } from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { getPortalSiteDisplayName, getPortalSiteSecondaryLabel } from '@/lib/portal-site-display';
import { formatDate, cn } from '@/lib/utils';

interface ApiKey {
  key_id: string;
  site_id: string;
  label: string;
  scopes: string[];
  status: 'active' | 'revoked' | 'expired';
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
}

interface ApiKeyWithSecret extends ApiKey {
  secret?: string;
  cloud_api_key?: string;
}

function KeysContent() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyWithSecret | null>(null);
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'revoked' | 'expired'>(
    () => (searchParams?.get('status') as 'all' | 'active' | 'revoked' | 'expired') || 'all'
  );
  const [keySearchQuery, setKeySearchQuery] = useState(() => searchParams?.get('q') || '');
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [siteActionNotice, setSiteActionNotice] = useState<string | null>(null);
  const [isActivatingSite, setIsActivatingSite] = useState(false);
  const [pendingAction, setPendingAction] = useState<'rotate' | 'revoke' | null>(null);
  const [isKeyActionLoading, setIsKeyActionLoading] = useState(false);
  const [siteSummary, setSiteSummary] = useState<PortalSiteSummaryRecord | null>(null);
  const [diagnostics, setDiagnostics] = useState<PortalSiteDiagnostics | null>(null);
  const [nowMs] = useState(() => Date.now());

  const loadKeys = useCallback(async () => {
    if (!selectedSiteId) return;

    setIsLoading(true);
    setError(null);

    try {
      const [response, summaryResponse, diagnosticsResponse] = await Promise.all([
        portalClient.listApiKeys(selectedSiteId),
        portalClient.getSiteSummary(selectedSiteId),
        portalClient.getSiteDiagnostics(selectedSiteId).catch(() => null),
      ]);
      setKeys(response.data.items || []);
      setSiteSummary(summaryResponse.data as PortalSiteSummaryRecord);
      setDiagnostics(diagnosticsResponse?.data || null);
    } catch (err) {
      setSiteSummary(null);
      setDiagnostics(null);
      setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [selectedSiteId, t]);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  useEffect(() => {
    if (keys.length === 0) {
      setSelectedKeyId('');
      return;
    }

    setSelectedKeyId((current) => {
      if (current && keys.some((key) => key.key_id === current)) {
        return current;
      }

      return keys.find((key) => key.status === 'active')?.key_id || keys[0]?.key_id || '';
    });
  }, [keys]);

  useEffect(() => {
    setStatusFilter((searchParams?.get('status') as 'all' | 'active' | 'revoked' | 'expired') || 'all');
    setKeySearchQuery(searchParams?.get('q') || '');
  }, [searchParams]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams?.toString() || '');
    if (statusFilter !== 'all') {
      params.set('status', statusFilter);
    } else {
      params.delete('status');
    }
    if (keySearchQuery.trim()) {
      params.set('q', keySearchQuery.trim());
    } else {
      params.delete('q');
    }
    const nextQuery = params.toString();
    const currentQuery = searchParams?.toString() || '';
    if (nextQuery !== currentQuery) {
      router.replace(`${pathname}${nextQuery ? `?${nextQuery}` : ''}`, { scroll: false });
    }
  }, [pathname, router, searchParams, statusFilter, keySearchQuery]);
  const filteredKeys = keys.filter((key) => {
    if (statusFilter !== 'all' && key.status !== statusFilter) {
      return false;
    }
    const query = keySearchQuery.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return (
      (key.label || '').toLowerCase().includes(query) ||
      key.key_id.toLowerCase().includes(query) ||
      key.scopes.some((scope) => scope.toLowerCase().includes(query))
    );
  });

  const handleCreateKey = async (label: string, scopes: string[], expiresAt?: string) => {
    if (!selectedSiteId || !canWriteKeys) return;

    try {
      const response = await portalClient.createApiKey(selectedSiteId, { label, scopes, expires_at: expiresAt });
      setNewKey(response.data);
      setShowCreateModal(false);
      await loadKeys();
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_create_api_key')));
    }
  };

  const handleActivateSite = async () => {
    if (!selectedSiteId || isActivatingSite || !canWriteKeys) return;

    setIsActivatingSite(true);
    setSiteActionError(null);
    setSiteActionNotice(null);
    try {
      await portalClient.activateSite(selectedSiteId);
      setSiteActionNotice(
        t(
          'portal.site_activation_success',
          {},
          'Site is now active. Addon signed probes and hosted runtime requests can proceed.'
        )
      );
      await loadKeys();
    } catch (err) {
      setSiteActionError(
        formatPortalErrorMessage(
          err,
          t,
          t('portal.site_activation_failed', {}, 'Failed to activate this site.')
        )
      );
    } finally {
      setIsActivatingSite(false);
    }
  };

  const fallbackCopyText = (text: string) => {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
      return document.execCommand('copy');
    } finally {
      document.body.removeChild(textarea);
    }
  };

  const handleCopy = async (text: string) => {
    setCopyError(null);
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const copiedWithFallback = fallbackCopyText(text);
        if (!copiedWithFallback) {
          throw new Error('clipboard_fallback_failed');
        }
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy credential:', error);
      setCopyError(
        t(
          'keys.copy_failed_notice',
          {},
          'Copy failed in this browser context. Use HTTPS or localhost, or copy the value manually.'
        )
      );
    }
  };

  const isProtectedSystemInitializedKey = (key: ApiKey | null | undefined) =>
    Boolean(key && (key.key_id === 'key_default' || key.label === 'seed-runtime'));

  const handleRotateKey = async () => {
    if (!selectedSiteId || !selectedKey || isKeyActionLoading || !canWriteKeys) return;

    setIsKeyActionLoading(true);
    setSiteActionError(null);
    setSiteActionNotice(null);
    try {
      const response = await portalClient.rotateApiKey(selectedSiteId, selectedKey.key_id, {
        label: selectedKey.label,
        scopes: selectedKey.scopes,
      });
      setNewKey(response.data.current || null);
      setPendingAction(null);
      setSiteActionNotice(
        t(
          'keys.rotate_success',
          {},
          'A new API key was issued and the previous key was revoked.'
        )
      );
      await loadKeys();
      if (response.data.current?.key_id) {
        setSelectedKeyId(response.data.current.key_id);
      }
    } catch (err) {
      setSiteActionError(
        formatPortalErrorMessage(
          err,
          t,
          t('keys.rotate_failed', {}, 'Failed to rotate this API key.')
        )
      );
    } finally {
      setIsKeyActionLoading(false);
    }
  };

  const handleRevokeKey = async () => {
    if (!selectedSiteId || !selectedKey || isKeyActionLoading || !canWriteKeys) return;

    if (isProtectedSystemInitializedKey(selectedKey)) {
      setPendingAction(null);
      setSiteActionError(
        t(
          'keys.revoke_protected_blocked',
          {},
          'This system-initialized key is protected. Create or rotate another key before changing it.'
        )
      );
      return;
    }

    setIsKeyActionLoading(true);
    setSiteActionError(null);
    setSiteActionNotice(null);
    try {
      await portalClient.revokeApiKey(selectedSiteId, selectedKey.key_id);
      setPendingAction(null);
      setSiteActionNotice(
        t(
          'keys.revoke_success',
          {},
          'The API key was revoked. Existing clients using this key will stop working immediately.'
        )
      );
      await loadKeys();
    } catch (err) {
      setSiteActionError(
        formatPortalErrorMessage(
          err,
          t,
          t('keys.revoke_failed', {}, 'Failed to revoke this API key.')
        )
      );
    } finally {
      setIsKeyActionLoading(false);
    }
  };

  if (sessionLoading || isLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (error && !keys.length) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => void loadKeys()}
      />
    );
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  const isReadOnlySession = false;
  const activeKeyCount = keys.filter((key) => key.status === 'active').length;
  const latestUsedKey = keys.find((key) => key.last_used_at);
  const selectedKey = keys.find((key) => key.key_id === selectedKeyId) || null;
  const siteCoverage = siteSummary?.coverage || null;
  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: siteCoverage?.plan_id || session.current_subscription?.plan_id,
    planVersionId: siteCoverage?.plan_version_id || session.current_subscription?.plan_version_id,
    packageAlias: siteCoverage?.package_alias || session.current_subscription?.package_alias,
    formalPlanName: selectedSite?.plan_name,
    planKind: session.current_subscription?.plan_kind,
    coverageState: siteCoverage || session.current_subscription ? 'covered' : 'uncovered',
  });
  const writeNotice = siteSummary?.allowed_actions?.includes('manage_site_keys')
    ? null
    : t(
        'keys.user_read_only_notice',
        {},
        'Your current user access is read-only. Ask a platform admin to grant key-management access before creating or rotating keys.'
      );
  const selectedKeyProtected = isProtectedSystemInitializedKey(selectedKey);
  const canManageSiteKeys = Boolean(siteSummary?.allowed_actions?.includes('manage_site_keys'));
  const canWriteKeys = canManageSiteKeys && !isReadOnlySession;
  const hasExpiringKey = keys.some((key) => {
    const expiresAtMs = key.expires_at ? new Date(key.expires_at).getTime() : 0;
    return key.status === 'active' && expiresAtMs > 0 && expiresAtMs - nowMs <= 1000 * 60 * 60 * 24 * 14;
  });
  const hasLongUnusedKey = keys.some((key) => {
    const lastUsedAtMs = key.last_used_at ? new Date(key.last_used_at).getTime() : 0;
    const createdAtMs = new Date(key.created_at).getTime();
    return (
      key.status === 'active' &&
      ((!key.last_used_at && Number.isFinite(createdAtMs) && nowMs - createdAtMs > 1000 * 60 * 60 * 24 * 30) ||
        (lastUsedAtMs > 0 && nowMs - lastUsedAtMs > 1000 * 60 * 60 * 24 * 60))
    );
  });
  const keyRecommendation =
    activeKeyCount === 0
      ? t(
          'keys.recommend_create_90d',
          {},
          '当前没有活跃密钥，建议创建一个 90 天密钥。'
        )
      : hasExpiringKey
        ? t('keys.recommend_rotate_expiring', {}, '有密钥即将过期，建议提前轮换。')
        : hasLongUnusedKey
          ? t('keys.recommend_review_unused', {}, '存在长期未使用的密钥，建议确认是否仍需要保留。')
          : t('keys.recommend_ok', {}, '当前密钥状态正常，继续关注最近使用时间即可。');
  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('keys.active_keys')}
        title={t('keys.title')}
        eyebrowInfo={t('portal.keys.primary_desc')}
        currentPage="keys"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={setSelectedSiteId}
        metrics={[
          { label: t('keys.active_keys'), value: activeKeyCount },
          {
            label: t('common.plan'),
            value: packageDisplay.display_package_label || t('common.not_found'),
          },
          {
            label: t('common.status'),
            value: isReadOnlySession
              ? t('common.read_only', {}, 'Read only')
              : selectedKey
                ? t(`status.${selectedKey.status}`, undefined, selectedKey.status)
                : t('common.not_found'),
          },
          {
            label: t('keys.last_used'),
            value: latestUsedKey?.last_used_at ? formatDate(latestUsedKey.last_used_at) : t('common.never'),
            size: 'compact',
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-4"
        primaryAction={
          selectedSite?.status === 'provisioning' ? (
            <button onClick={() => void handleActivateSite()} className="btn btn-primary" disabled={isActivatingSite}>
              {isActivatingSite
                ? t('common.saving')
                : t('portal.activate_site_action', {}, 'Activate site')}
            </button>
          ) : (
            <button
              onClick={() => setShowCreateModal(true)}
              className="btn btn-primary"
              disabled={!canWriteKeys}
              title={writeNotice || undefined}
            >
              + {t('keys.create_short', {}, 'Create key')}
            </button>
          )
        }
        secondaryActions={
          selectedSite?.status === 'provisioning' ? (
            <button
              onClick={() => setShowCreateModal(true)}
              className="btn btn-secondary"
              disabled={!canWriteKeys}
              title={writeNotice || undefined}
            >
              + {t('keys.create_short', {}, 'Create key')}
            </button>
          ) : null
        }
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSite?.site_name || selectedSiteId },
            `正在切换到 ${switchingSiteName || selectedSite?.site_name || selectedSiteId}，页面数据会自动更新。`
          )}
        />
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
            <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('keys.title')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('keys.total', { count: String(filteredKeys.length) })}
            </h2>
          </div>
          <div className="overflow-x-auto">
            <div className="flex flex-col gap-3 border-b border-gray-200 px-6 py-4 dark:border-gray-800 lg:flex-row lg:items-center lg:justify-between">
              <input
                type="search"
                value={keySearchQuery}
                onChange={(event) => setKeySearchQuery(event.target.value)}
                placeholder={t('portal.keys.search_placeholder', {}, 'Search label, key ID, or scope')}
                className="input w-full lg:max-w-sm"
              />
              <div className="flex flex-wrap gap-2">
              <button type="button" className={`btn btn-sm ${statusFilter === 'all' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setStatusFilter('all')}>
                {t('common.all', {}, 'All')}
              </button>
              <button type="button" className={`btn btn-sm ${statusFilter === 'active' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setStatusFilter('active')}>
                {t('status.active')}
              </button>
              <button type="button" className={`btn btn-sm ${statusFilter === 'revoked' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setStatusFilter('revoked')}>
                {t('status.revoked', {}, 'Revoked')}
              </button>
              <button type="button" className={`btn btn-sm ${statusFilter === 'expired' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setStatusFilter('expired')}>
                {t('status.expired', {}, 'Expired')}
              </button>
              </div>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50/80 dark:bg-gray-900/60">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('keys.label')}</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('keys.scopes')}</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('keys.last_used')}</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('keys.status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredKeys.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8">
                      <div className="space-y-4 text-center">
                        <PortalEmptyState
                          title={t('portal.keys.empty_title', {}, 'No keys for this site')}
                          description={
                            selectedSite?.status === 'provisioning'
                              ? t(
                                  'portal.keys.empty_provisioning_desc',
                                  {},
                                  'This site is still provisioning. Activate it or create the first key to finish setup.'
                                )
                              : t(
                                  'portal.keys.empty_desc',
                                  {},
                                  'This site does not have an API key yet. Create the first key to begin hosted runtime access.'
                                )
                          }
                          actionButton={
                            <button
                              type="button"
                              className="btn btn-primary"
                              disabled={!canWriteKeys}
                              onClick={() => setShowCreateModal(true)}
                              title={writeNotice || undefined}
                            >
                              {t('keys.create_short', {}, 'Create key')}
                            </button>
                          }
                        />
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredKeys.map((key) => {
                    const isSelected = key.key_id === selectedKeyId;
                    const expiresAtMs = key.expires_at ? new Date(key.expires_at).getTime() : 0;
                    const isExpiringSoon = key.status === 'active' && expiresAtMs > 0 && expiresAtMs - nowMs <= 1000 * 60 * 60 * 24 * 14;
                    const createdAtMs = new Date(key.created_at).getTime();
                    const isLongUnused = key.status === 'active' && !key.last_used_at && Number.isFinite(createdAtMs) && nowMs - createdAtMs > 1000 * 60 * 60 * 24 * 30;
                    return (
                      <tr
                        key={key.key_id}
                        className={cn(
                          'cursor-pointer transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/50',
                          isSelected && 'bg-[color:var(--surface-raised)] ring-1 ring-inset ring-[color:var(--brand-primary-soft)]'
                        )}
                        onClick={() => setSelectedKeyId(key.key_id)}
                      >
                        <td className="px-4 py-3">
                          <p className="font-medium">{key.label || t('keys.unnamed')}</p>
                          <BackofficeIdentifier value={key.key_id} className="mt-1 block text-xs text-gray-500" />
                          <div className="mt-2 flex flex-wrap gap-1">
                            {isExpiringSoon ? <BackofficeTag tone="warning">{t('keys.expiring_soon', {}, '即将过期')}</BackofficeTag> : null}
                            {!key.last_used_at ? <BackofficeTag tone="warning">{t('keys.never_used', {}, '从未使用')}</BackofficeTag> : null}
                            {isLongUnused ? <BackofficeTag tone="warning">{t('keys.long_unused', {}, '长期未使用')}</BackofficeTag> : null}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {key.scopes.slice(0, 2).map((scope) => (
                              <BackofficeTag key={scope} tone="info">
                                {scope}
                              </BackofficeTag>
                            ))}
                            {key.scopes.length > 2 ? (
                              <span className="text-xs text-gray-500 dark:text-gray-400">+{key.scopes.length - 2}</span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {key.last_used_at ? formatDate(key.last_used_at) : t('common.never')}
                        </td>
                        <td className="px-4 py-3">
                          <BackofficeStatusBadge status={key.status} label={t(`status.${key.status}`, undefined, key.status)} />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <BackofficeStackCard className="border-blue-200 bg-blue-50/70 text-blue-950 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-100">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">
              {t('keys.recommendation_label', {}, '推荐动作')}
            </p>
            <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm leading-6">{keyRecommendation}</p>
              {activeKeyCount === 0 ? (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!canWriteKeys}
                  onClick={() => setShowCreateModal(true)}
                  title={writeNotice || undefined}
                >
                  {t('keys.create_short', {}, 'Create key')}
                </button>
              ) : null}
            </div>
          </BackofficeStackCard>
          {writeNotice ? (
            <BackofficeStackCard className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
              <p className="text-xs uppercase tracking-[0.18em] text-amber-700 dark:text-amber-300">{t('common.notice')}</p>
              <p className="mt-2 text-sm leading-7">{writeNotice}</p>
            </BackofficeStackCard>
          ) : null}
          {selectedSite?.status === 'provisioning' ? (
            <BackofficeStackCard className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
              <p className="text-xs uppercase tracking-[0.18em] text-amber-700 dark:text-amber-300">
                {t('status.provisioning')}
              </p>
              <p className="mt-2 text-sm leading-7">
                {t(
                  'portal.provisioning_notice',
                  {},
                  'This site is still provisioning. Activate it here or issue the first API key to complete hosted runtime setup.'
                )}
              </p>
            </BackofficeStackCard>
          ) : null}
          {siteActionNotice ? (
            <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-100">
              <p className="text-sm leading-7">{siteActionNotice}</p>
            </BackofficeStackCard>
          ) : null}
          {siteActionError ? (
            <BackofficeStackCard className="border-red-200 bg-red-50 text-red-900 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-100">
              <p className="text-sm leading-7">{siteActionError}</p>
            </BackofficeStackCard>
          ) : null}
          <BackofficeStackCard>
            <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.keys.selected_key_label', {}, 'Selected key')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {selectedKey?.label || t('keys.unnamed')}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {selectedKey?.key_id ? (
                <BackofficeIdentifier value={selectedKey.key_id} full className="text-sm" />
              ) : (
                <p className="text-sm text-gray-600 dark:text-gray-400">{t('common.not_found')}</p>
              )}
              {selectedKey ? (
                <BackofficeFilterPill
                  onClick={() => void handleCopy(selectedKey.key_id)}
                  active={copied}
                  tone="info"
                >
                  {copied ? t('keys.copied') : t('keys.copy_id')}
                </BackofficeFilterPill>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {selectedKey ? (
                <BackofficeStatusBadge
                  status={selectedKey.status}
                  label={t(`status.${selectedKey.status}`, undefined, selectedKey.status)}
                />
              ) : null}
              {selectedKey?.expires_at ? (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {t('keys.expires')}: {formatDate(selectedKey.expires_at)}
                </span>
              ) : null}
            </div>
            <div className="mt-4 space-y-3 text-sm text-gray-600 dark:text-gray-300">
              <p>
                {selectedKey?.last_used_at
                  ? `${t('keys.last_used')}: ${formatDate(selectedKey.last_used_at)}`
                  : `${t('common.created')}: ${selectedKey?.created_at ? formatDate(selectedKey.created_at) : t('common.not_found')}`}
              </p>
              <div className="flex flex-wrap gap-2">
                {selectedKey?.scopes.map((scope) => (
                  <BackofficeTag key={scope} tone="info">
                    {scope}
                  </BackofficeTag>
                ))}
                {!selectedKey?.scopes.length ? (
                  <span className="text-sm text-gray-500 dark:text-gray-400">{t('common.not_found')}</span>
                ) : null}
              </div>
            </div>
            {selectedKey ? (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setPendingAction('rotate')}
                  className="btn btn-secondary btn-sm"
                  disabled={!canWriteKeys || isKeyActionLoading || selectedKey.status !== 'active'}
                  title={writeNotice || undefined}
                >
                  {t('keys.rotate', {}, 'Rotate')}
                </button>
                <button
                  type="button"
                  onClick={() => setPendingAction('revoke')}
                  className="btn btn-secondary btn-sm"
                  disabled={!canWriteKeys || isKeyActionLoading || selectedKey.status !== 'active' || selectedKeyProtected}
                  title={
                    writeNotice ||
                    (selectedKeyProtected
                      ? t(
                          'keys.revoke_protected_hint',
                          {},
                          'Default bootstrap keys are protected. Create or rotate another key first.'
                        )
                      : undefined)
                  }
                >
                  {t('keys.revoke', {}, 'Revoke')}
                </button>
              </div>
            ) : null}
            {selectedKeyProtected ? (
              <p className="mt-3 text-xs text-amber-700 dark:text-amber-300">
                {t(
                  'keys.revoke_protected_hint',
                  {},
                  'Default bootstrap keys are protected. Create or rotate another key first.'
                )}
              </p>
            ) : null}
          </BackofficeStackCard>

          {diagnostics?.checks?.length ? (
            <BackofficeStackCard>
              <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.diagnostics.label', {}, '接入诊断')}
              </p>
              <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
                {t('portal.diagnostics.title', {}, '当前站点接入状态')}
              </h2>
              <div className="mt-4 space-y-3">
                {diagnostics.checks.map((check) => (
                  <div key={check.key} className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">{check.title}</p>
                      <BackofficeStatusBadge status={check.status} label={check.status} />
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{check.detail}</p>
                    {check.action ? <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{check.action}</p> : null}
                  </div>
                ))}
              </div>
            </BackofficeStackCard>
          ) : null}

        </BackofficeSectionPanel>
      </div>

      <CreateKeyModal
        isOpen={showCreateModal}
        siteLabel={getPortalSiteDisplayName(selectedSite) || selectedSiteId || t('common.not_found')}
        siteId={getPortalSiteSecondaryLabel(selectedSite) || selectedSiteId}
        onClose={() => setShowCreateModal(false)}
        onCreate={handleCreateKey}
      />

      <NewKeyDisplayModal
        isOpen={Boolean(newKey)}
        keyData={newKey}
        onClose={() => setNewKey(null)}
        onCopy={handleCopy}
        copied={copied}
        copyError={copyError}
      />

      <Modal
        isOpen={pendingAction === 'rotate'}
        onClose={() => setPendingAction(null)}
        title={t('keys.rotate_confirm_title', {}, 'Rotate this API key?')}
        description={t(
          'keys.rotate_confirm_desc',
          {},
          'Rotation creates a new active key and immediately revokes the current key. Update any clients using the old key.'
        )}
        size="md"
      >
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => setPendingAction(null)} className="btn btn-secondary" disabled={isKeyActionLoading}>
            {t('common.cancel')}
          </button>
          <button type="button" onClick={() => void handleRotateKey()} className="btn btn-primary" disabled={isKeyActionLoading}>
            {isKeyActionLoading ? t('common.saving') : t('keys.rotate', {}, 'Rotate')}
          </button>
        </div>
      </Modal>

      <Modal
        isOpen={pendingAction === 'revoke'}
        onClose={() => setPendingAction(null)}
        title={t('keys.revoke_confirm_title', {}, 'Revoke this API key?')}
        description={t(
          'keys.revoke_confirm_desc',
          {},
          'Revoking a key disables it immediately. Existing clients using this key will fail until they switch to another active key.'
        )}
        size="md"
      >
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => setPendingAction(null)} className="btn btn-secondary" disabled={isKeyActionLoading}>
            {t('common.cancel')}
          </button>
          <button type="button" onClick={() => void handleRevokeKey()} className="btn btn-primary" disabled={isKeyActionLoading || selectedKeyProtected}>
            {isKeyActionLoading ? t('common.saving') : t('keys.revoke', {}, 'Revoke')}
          </button>
        </div>
      </Modal>
    </BackofficePageStack>
  );
}

// Create Key Modal Component
function CreateKeyModal({
  isOpen,
  siteLabel,
  siteId,
  onClose,
  onCreate,
}: {
  isOpen: boolean;
  siteLabel: string;
  siteId: string;
  onClose: () => void;
  onCreate: (label: string, scopes: string[], expiresAt?: string) => void;
}) {
  const { t } = useLocale();
  const [label, setLabel] = useState('');
  const keyPresets = [
    {
      id: 'standard',
      label: t('keys.preset_standard'),
      description: t('keys.preset_standard_desc'),
      scopes: ['catalog:read', 'runtime:resolve', 'runtime:execute', 'runtime:read', 'stats:read', 'entitlement:read'],
    },
    {
      id: 'readonly',
      label: t('keys.preset_readonly'),
      description: t('keys.preset_readonly_desc'),
      scopes: ['catalog:read', 'runtime:read', 'stats:read', 'entitlement:read'],
    },
  ] as const;
  const [presetId, setPresetId] = useState<(typeof keyPresets)[number]['id']>('standard');
  const [expiryDays, setExpiryDays] = useState('90');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const selectedPreset = keyPresets.find((preset) => preset.id === presetId) || keyPresets[0];
    const days = Number.parseInt(expiryDays, 10);
    const expiresAt = Number.isFinite(days) && days > 0
      ? new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString()
      : undefined;
    onCreate(label, [...selectedPreset.scopes], expiresAt);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('keys.create_modal_title')}
      description={t('keys.create_modal_desc')}
      size="lg"
    >
      <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('keys.site_access')}</p>
      <p className="mt-3 text-sm font-medium text-gray-950 dark:text-white">{siteLabel}</p>
      <p className="mb-4 mt-1 text-sm text-gray-600 dark:text-gray-400">{siteId}</p>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium mb-1">{t('keys.label')}</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('keys.create_placeholder')}
              className="input w-full"
              required
            />
          </div>
          <div className="mb-4">
            <label className="block text-sm font-medium mb-1">{t('keys.scopes')}</label>
            <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">{t('keys.create_modal_scopes_desc')}</p>
            <div className="space-y-3">
              {keyPresets.map((preset) => {
                const active = presetId === preset.id;
                return (
                  <label
                    key={preset.id}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-2xl border px-4 py-3 transition',
                      active
                        ? 'border-blue-500 bg-blue-50/70 dark:border-blue-400 dark:bg-blue-950/30'
                        : 'border-gray-200 bg-white/70 hover:border-gray-300 dark:border-gray-800 dark:bg-gray-950/40 dark:hover:border-gray-700'
                    )}
                  >
                    <input
                      type="radio"
                      name="key-preset"
                      value={preset.id}
                      checked={active}
                      onChange={() => setPresetId(preset.id)}
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-950 dark:text-white">{preset.label}</p>
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{preset.description}</p>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-sm font-medium mb-1">{t('keys.expires', {}, 'Expires')}</label>
            <select className="input w-full" value={expiryDays} onChange={(event) => setExpiryDays(event.target.value)}>
              <option value="90">{t('keys.expiry_90_days', {}, '90 天后过期')}</option>
              <option value="180">{t('keys.expiry_180_days', {}, '180 天后过期')}</option>
              <option value="365">{t('keys.expiry_365_days', {}, '365 天后过期')}</option>
              <option value="0">{t('keys.expiry_none', {}, '不设置过期时间')}</option>
            </select>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn btn-secondary">
              {t('common.cancel')}
            </button>
            <button type="submit" className="btn btn-primary">
              {t('common.create')}
            </button>
          </div>
        </form>
    </Modal>
  );
}

// New Key Display Modal
function NewKeyDisplayModal({
  isOpen,
  keyData,
  onClose,
  onCopy,
  copied,
  copyError,
}: {
  isOpen: boolean;
  keyData: ApiKeyWithSecret | null;
  onClose: () => void;
  onCopy: (text: string) => void;
  copied: boolean;
  copyError: string | null;
}) {
  const { t } = useLocale();
  if (!keyData) {
    return null;
  }
  const primaryCredential = keyData.cloud_api_key || keyData.secret || '';
  const showRawSecret = Boolean(
    keyData.secret && keyData.cloud_api_key && keyData.secret !== keyData.cloud_api_key
  );
  const primaryLabel = keyData.cloud_api_key
    ? t('keys.cloud_key')
    : t('keys.secret_plaintext', {}, 'Raw secret');
  const description = keyData.cloud_api_key
    ? t(
        'keys.secret_created_desc_cloud',
        {},
        'Copy this Cloud API Key now. It will not be shown again after you close this dialog.'
      )
    : t('keys.secret_created_desc');
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('keys.secret_created_title')}
      description={description}
      size="lg"
    >
        <div className="mb-4">
          <p className="mb-2 text-sm text-gray-600 dark:text-gray-400">{primaryLabel}</p>
          <div className="flex items-center gap-2 p-3 bg-gray-100 dark:bg-gray-900 rounded-md font-mono text-sm break-all">
            <code className="flex-1">{primaryCredential}</code>
            <button
              onClick={() => onCopy(primaryCredential)}
              className="text-blue-600 hover:underline text-sm whitespace-nowrap"
              disabled={!primaryCredential}
            >
              {copied ? t('keys.copied') : t('keys.copy_secret')}
            </button>
          </div>
        </div>

        {showRawSecret && (
          <div className="mb-4">
            <p className="mb-2 text-sm text-gray-600 dark:text-gray-400">
              {t('keys.secret_plaintext', {}, 'Raw secret')}
            </p>
            <div className="flex items-center gap-2 p-3 bg-gray-100 dark:bg-gray-900 rounded-md font-mono text-sm break-all">
              <code className="flex-1">{keyData.secret}</code>
              <button
                onClick={() => onCopy(keyData.secret!)}
                className="text-blue-600 hover:underline text-sm whitespace-nowrap"
              >
                {t('keys.copy_secret')}
              </button>
            </div>
          </div>
        )}

        {copyError ? (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
            {copyError}
          </div>
        ) : null}

        <div className="flex justify-end">
          <button onClick={onClose} className="btn btn-primary">{t('common.done')}</button>
        </div>
    </Modal>
  );
}

export default function ApiKeysPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <KeysContent />
    </Suspense>
  );
}
