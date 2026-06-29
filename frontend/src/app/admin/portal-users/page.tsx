'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ConfirmModal, Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { cn, formatDate } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type PortalUserItem = {
  principal_id: string;
  email: string;
  status: string;
  session_version: number;
  source: string;
  created_at?: string;
  last_login_at?: string;
  account_id?: string;
  account_name?: string;
  account_status?: string;
  membership_status?: string;
  site_id?: string;
  site_name?: string;
  site_status?: string;
  wordpress_url?: string;
  grant_status?: string;
  subscription_id?: string;
  subscription_status?: string;
  plan_id?: string;
  package_alias?: string;
  display_package_label?: string;
  qq_bound: boolean;
  qq_binding_count: number;
  qq_last_login_at?: string;
};

type PortalUsersSummary = {
  active?: number;
  disabled?: number;
  qq_bound?: number;
  self_registered?: number;
};

type PortalUsersResponse = {
  items?: PortalUserItem[];
  total?: number;
  summary?: PortalUsersSummary;
};

type PortalUserAuditEvent = {
  event_id: number;
  event_kind: string;
  outcome: string;
  actor_kind: string;
  actor_ref: string;
  method: string;
  path: string;
  trace_id: string;
  idempotency_key: string;
  scope_kind: string;
  scope_id: string;
  account_id?: string;
  site_id?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

type PortalUserAuditDetail = {
  principal?: {
    principal_id?: string;
    email?: string;
    status?: string;
    session_version?: number;
    last_login_at?: string;
    created_at?: string;
  };
  items?: PortalUserAuditEvent[];
  total?: number;
  summary?: {
    events?: number;
    succeeded?: number;
    failed?: number;
    registration_events?: number;
    disable_events?: number;
    latest_disable_reason?: string;
    latest_disable_revoked_site_grants?: number;
    latest_disable_revoked_account_memberships?: number;
    latest_disable_revoked_identity_provider_bindings?: number;
  };
};

type BatchDisableResult = {
  totals?: {
    attempted?: number;
    disabled?: number;
    already_disabled?: number;
    failed?: number;
  };
  items?: Array<{
    principal_id?: string;
    outcome?: string;
    status?: string;
    session_version?: number;
    error_code?: string;
    message?: string;
  }>;
};

type Filters = {
  q: string;
  status: string;
  package_alias: string;
  qq_bound: string;
};

function sourceLabel(source: string): string {
  if (source === 'portal_self_registration') {
    return '自助注册';
  }
  if (source === 'principal_access') {
    return '后台开通';
  }
  return source || '未知';
}

function dateLabel(value?: string): string {
  return value ? formatDate(value) : '未记录';
}

function auditEventLabel(eventKind: string): string {
  if (eventKind === 'portal.registration') {
    return '自助注册';
  }
  if (eventKind === 'portal_user.disable') {
    return '禁用用户';
  }
  if (eventKind === 'principal_access.upsert') {
    return '访问开通';
  }
  return eventKind || '未知事件';
}

function payloadText(payload?: Record<string, unknown>): string {
  if (!payload) {
    return '';
  }
  const reason = String(payload.reason || '').trim();
  const revokedSiteGrants = Number(payload.revoked_site_grants || 0);
  const revokedMemberships = Number(payload.revoked_account_memberships || 0);
  const revokedBindings = Number(payload.revoked_identity_provider_bindings || 0);
  if (reason || revokedSiteGrants || revokedMemberships || revokedBindings) {
    return [
      reason ? `原因：${reason}` : '',
      revokedSiteGrants ? `站点授权 ${revokedSiteGrants}` : '',
      revokedMemberships ? `账号成员 ${revokedMemberships}` : '',
      revokedBindings ? `QQ 绑定 ${revokedBindings}` : '',
    ].filter(Boolean).join(' · ');
  }
  const email = String(payload.email || '').trim();
  const siteId = String(payload.site_id || '').trim();
  if (email || siteId) {
    return [email ? `邮箱：${email}` : '', siteId ? `站点：${siteId}` : ''].filter(Boolean).join(' · ');
  }
  return '';
}

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  params.set('source', 'portal_self_registration');
  params.set('limit', '200');
  if (filters.q.trim()) params.set('q', filters.q.trim());
  if (filters.status) params.set('status', filters.status);
  if (filters.package_alias.trim()) params.set('package_alias', filters.package_alias.trim());
  if (filters.qq_bound) params.set('qq_bound', filters.qq_bound);
  return params.toString();
}

export default function AdminPortalUsersPage() {
  const { t } = useLocale();
  const [users, setUsers] = useState<PortalUserItem[]>([]);
  const [summary, setSummary] = useState<PortalUsersSummary>({});
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<Filters>({
    q: '',
    status: '',
    package_alias: '',
    qq_bound: '',
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingUser, setPendingUser] = useState<PortalUserItem | null>(null);
  const [disableReason, setDisableReason] = useState('');
  const [savingPrincipalId, setSavingPrincipalId] = useState<string | null>(null);
  const [auditUser, setAuditUser] = useState<PortalUserItem | null>(null);
  const [auditDetail, setAuditDetail] = useState<PortalUserAuditDetail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [selectedPrincipalIds, setSelectedPrincipalIds] = useState<string[]>([]);
  const [batchDisableOpen, setBatchDisableOpen] = useState(false);
  const [batchDisableReason, setBatchDisableReason] = useState('');
  const [batchSaving, setBatchSaving] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/portal-users?${buildQuery(filters)}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || '加载自助注册用户失败');
      }
      const data = (payload.data || {}) as PortalUsersResponse;
      setUsers(Array.isArray(data.items) ? data.items : []);
      setSummary(data.summary || {});
      setTotal(Number(data.total || 0));
      setSelectedPrincipalIds((current) => {
        const nextIds = new Set((data.items || []).map((item) => item.principal_id));
        return current.filter((principalId) => nextIds.has(principalId));
      });
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, '加载自助注册用户失败'));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const visibleMetricItems = useMemo(
    () => [
      { label: '筛选结果', value: total },
      { label: '正常', value: summary.active || 0, toneClassName: 'text-emerald-700 dark:text-emerald-200' },
      { label: '已禁用', value: summary.disabled || 0, toneClassName: 'text-slate-700 dark:text-slate-200' },
      { label: '已绑 QQ', value: summary.qq_bound || 0, toneClassName: 'text-blue-700 dark:text-blue-200' },
    ],
    [summary.active, summary.disabled, summary.qq_bound, total]
  );

  const updateFilter = (key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const clearFilters = () => {
    setFilters({
      q: '',
      status: '',
      package_alias: '',
      qq_bound: '',
    });
  };

  const activeUsers = users.filter((user) => user.status !== 'disabled');
  const selectedActiveUsers = users.filter((user) => selectedPrincipalIds.includes(user.principal_id));
  const allActiveSelected =
    activeUsers.length > 0 && activeUsers.every((user) => selectedPrincipalIds.includes(user.principal_id));

  const toggleUserSelection = (principalId: string) => {
    setSelectedPrincipalIds((current) =>
      current.includes(principalId)
        ? current.filter((item) => item !== principalId)
        : [...current, principalId]
    );
  };

  const toggleAllActiveUsers = () => {
    if (allActiveSelected) {
      setSelectedPrincipalIds([]);
      return;
    }
    setSelectedPrincipalIds(activeUsers.map((user) => user.principal_id));
  };

  const disableUser = async (user: PortalUserItem) => {
    setSavingPrincipalId(user.principal_id);
    setNotice(null);
    setActionError(null);
    try {
      const response = await fetch(
        `/api/admin/portal-users/${encodeURIComponent(user.principal_id)}/disable`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: disableReason.trim() }),
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || '禁用用户失败');
      }
      setUsers((current) =>
        current.map((item) =>
          item.principal_id === user.principal_id
            ? {
                ...item,
                status: 'disabled',
                membership_status: 'revoked',
                grant_status: 'revoked',
                qq_bound: false,
                qq_binding_count: 0,
                session_version: Number(payload.data?.session_version || item.session_version),
              }
            : item
        )
      );
      setNotice(`${user.email || user.principal_id} 已禁用，现有 Portal 会话和 QQ 绑定已失效。`);
      setDisableReason('');
      void loadUsers();
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, '禁用用户失败'));
    } finally {
      setSavingPrincipalId(null);
    }
  };

  const loadAuditDetail = async (user: PortalUserItem) => {
    setAuditUser(user);
    setAuditDetail(null);
    setAuditError(null);
    setAuditLoading(true);
    try {
      const response = await fetch(
        `/api/admin/portal-users/${encodeURIComponent(user.principal_id)}/audit?limit=50`,
        { credentials: 'include' }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || '加载用户审计失败');
      }
      setAuditDetail((payload.data || {}) as PortalUserAuditDetail);
    } catch (err) {
      setAuditError(resolveUiErrorMessage(err instanceof Error ? err.message : null, '加载用户审计失败'));
    } finally {
      setAuditLoading(false);
    }
  };

  const batchDisableUsers = async () => {
    const principalIds = selectedActiveUsers.map((user) => user.principal_id);
    const reason = batchDisableReason.trim();
    if (!reason) {
      setActionError('批量禁用需要填写原因。');
      return;
    }
    if (principalIds.length === 0) {
      setActionError('请选择至少一个正常用户。');
      return;
    }
    setBatchSaving(true);
    setNotice(null);
    setActionError(null);
    try {
      const response = await fetch('/api/admin/portal-users/batch-disable', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          principal_ids: principalIds,
          reason,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || '批量禁用失败');
      }
      const data = (payload.data || {}) as BatchDisableResult;
      const disabledIds = new Set(
        (data.items || [])
          .filter((item) => item.outcome === 'disabled' || item.outcome === 'already_disabled')
          .map((item) => String(item.principal_id || ''))
          .filter(Boolean)
      );
      setUsers((current) =>
        current.map((item) =>
          disabledIds.has(item.principal_id)
            ? {
                ...item,
                status: 'disabled',
                membership_status: 'revoked',
                grant_status: 'revoked',
                qq_bound: false,
                qq_binding_count: 0,
              }
            : item
        )
      );
      setSelectedPrincipalIds([]);
      setBatchDisableOpen(false);
      setBatchDisableReason('');
      const attempted = Number(data.totals?.attempted || principalIds.length);
      const failed = Number(data.totals?.failed || 0);
      setNotice(`批量禁用已处理 ${attempted} 个用户，失败 ${failed} 个。`);
      void loadUsers();
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, '批量禁用失败'));
    } finally {
      setBatchSaving(false);
    }
  };

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Portal Users"
        title="自助注册用户"
        description="查看用户端自助注册后自动开通的免费账号、站点、套餐和 QQ 绑定状态。"
        actions={
          <div className="grid w-full gap-3 md:grid-cols-[minmax(12rem,1.5fr)_minmax(8rem,0.8fr)_minmax(8rem,0.8fr)_minmax(8rem,0.8fr)_auto]">
            <input
              value={filters.q}
              onChange={(event) => updateFilter('q', event.target.value)}
              className="input h-11"
              placeholder="邮箱、账号、站点或域名"
            />
            <select
              value={filters.status}
              onChange={(event) => updateFilter('status', event.target.value)}
              className="input h-11"
              aria-label="用户状态"
            >
              <option value="">全部状态</option>
              <option value="active">正常</option>
              <option value="disabled">已禁用</option>
            </select>
            <input
              value={filters.package_alias}
              onChange={(event) => updateFilter('package_alias', event.target.value)}
              className="input h-11"
              placeholder="套餐"
            />
            <select
              value={filters.qq_bound}
              onChange={(event) => updateFilter('qq_bound', event.target.value)}
              className="input h-11"
              aria-label="QQ 绑定状态"
            >
              <option value="">QQ 全部</option>
              <option value="true">已绑定</option>
              <option value="false">未绑定</option>
            </select>
            <button type="button" onClick={clearFilters} className="btn btn-secondary h-11">
              清空
            </button>
          </div>
        }
        summary={<BackofficeMetricStrip items={visibleMetricItems} columnsClassName="xl:grid-cols-4" />}
      />

      {notice ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}
      {actionError || error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/25 dark:text-rose-200">
          {actionError || error}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-200 sm:flex-row sm:items-center sm:justify-between">
        <div>
          已选择 <span className="font-semibold text-slate-950 dark:text-white">{selectedPrincipalIds.length}</span> 个正常用户
        </div>
        <button
          type="button"
          className="btn btn-secondary self-start sm:self-auto"
          disabled={selectedPrincipalIds.length === 0}
          onClick={() => setBatchDisableOpen(true)}
        >
          批量禁用
        </button>
      </div>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        {loading ? (
          <div className="p-8">
            <LoadingFallback />
          </div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center">
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">暂无自助注册用户</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              新用户通过 Portal 注册并开通免费套餐后会出现在这里。
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50/80 dark:bg-slate-950/40">
                <tr>
                  <th className="w-12 px-5 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={allActiveSelected}
                      disabled={activeUsers.length === 0}
                      onChange={toggleAllActiveUsers}
                      aria-label="选择全部正常用户"
                    />
                  </th>
                  {['用户', '账号 / 站点', '套餐', 'QQ', '时间', '操作'].map((heading) => (
                    <th
                      key={heading}
                      className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400"
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white/75 dark:divide-slate-800 dark:bg-slate-950/25">
                {users.map((user) => (
                  <tr key={user.principal_id} className="align-top">
                    <td className="px-5 py-4">
                      <input
                        type="checkbox"
                        checked={selectedPrincipalIds.includes(user.principal_id)}
                        disabled={user.status === 'disabled'}
                        onChange={() => toggleUserSelection(user.principal_id)}
                        aria-label={`选择 ${user.email || user.principal_id}`}
                      />
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div className="font-semibold text-slate-950 dark:text-white">
                          {user.email || user.principal_id}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {user.principal_id}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <BackofficeStatusBadge
                            label={user.status === 'disabled' ? '已禁用' : '正常'}
                            status={user.status}
                          />
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                            {sourceLabel(user.source)}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div>
                          <div className="font-medium text-slate-900 dark:text-slate-100">
                            {user.account_name || user.account_id || '未绑定账号'}
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {user.account_id || '无账号 ID'} · {user.membership_status || '无成员状态'}
                          </div>
                        </div>
                        <div>
                          {user.site_id ? (
                            <Link
                              href={`/admin/sites/${encodeURIComponent(user.site_id)}`}
                              className="font-medium text-blue-700 hover:text-blue-600 dark:text-blue-300"
                            >
                              {user.site_name || user.site_id}
                            </Link>
                          ) : (
                            <span className="font-medium text-slate-700 dark:text-slate-200">未绑定站点</span>
                          )}
                          <div className="max-w-xs truncate text-xs text-slate-500 dark:text-slate-400">
                            {user.wordpress_url || user.site_id || '无站点 URL'} · {user.grant_status || '无授权状态'}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div className="font-medium text-slate-900 dark:text-slate-100">
                          {user.display_package_label || user.package_alias || user.plan_id || '未覆盖'}
                        </div>
                        <BackofficeStatusBadge
                          label={user.subscription_status || '无订阅'}
                          status={user.subscription_status || 'inactive'}
                        />
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <BackofficeStatusBadge
                          label={user.qq_bound ? '已绑定' : '未绑定'}
                          status={user.qq_bound ? 'active' : 'inactive'}
                        />
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {user.qq_bound ? `绑定数 ${user.qq_binding_count}` : '未启用快捷登录'}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-600 dark:text-slate-300">
                      <div>注册：{dateLabel(user.created_at)}</div>
                      <div>登录：{dateLabel(user.last_login_at)}</div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="btn btn-secondary"
                          onClick={() => {
                            void loadAuditDetail(user);
                          }}
                        >
                          审计
                        </button>
                        <button
                          type="button"
                          className={cn('btn btn-secondary', user.status === 'disabled' && 'opacity-60')}
                          disabled={user.status === 'disabled' || savingPrincipalId === user.principal_id}
                          onClick={() => setPendingUser(user)}
                        >
                          {savingPrincipalId === user.principal_id ? '处理中' : '禁用'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </BackofficeSectionPanel>

      {pendingUser ? (
        <ConfirmModal
          isOpen={Boolean(pendingUser)}
          title="确认禁用用户"
          message={`禁用 ${pendingUser.email || pendingUser.principal_id} 后，现有 Portal 会话、站点授权、账号成员关系和 QQ 快捷登录绑定都会失效。`}
          confirmLabel={t('common.confirm', {}, 'Confirm')}
          cancelLabel={t('common.cancel', {}, 'Cancel')}
          variant="danger"
          onClose={() => {
            setPendingUser(null);
            setDisableReason('');
          }}
          onConfirm={() => {
            void disableUser(pendingUser);
          }}
        >
          <textarea
            value={disableReason}
            onChange={(event) => setDisableReason(event.target.value)}
            className="input min-h-[5.5rem]"
            placeholder="原因，可选"
          />
        </ConfirmModal>
      ) : null}

      {batchDisableOpen ? (
        <Modal
          isOpen={batchDisableOpen}
          title="批量禁用用户"
          description={`将禁用 ${selectedPrincipalIds.length} 个用户。`}
          size="md"
          onClose={() => {
            if (!batchSaving) {
              setBatchDisableOpen(false);
              setBatchDisableReason('');
            }
          }}
          footer={
            <>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={batchSaving}
                onClick={() => {
                  setBatchDisableOpen(false);
                  setBatchDisableReason('');
                }}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={batchSaving || !batchDisableReason.trim() || selectedPrincipalIds.length === 0}
                onClick={() => {
                  void batchDisableUsers();
                }}
              >
                {batchSaving ? '处理中' : '确认禁用'}
              </button>
            </>
          }
        >
          <div className="space-y-4">
            <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
              批量禁用会让选中用户的 Portal 会话失效，并撤销站点授权、账号成员关系和 QQ 快捷登录绑定。
            </p>
            <textarea
              value={batchDisableReason}
              onChange={(event) => setBatchDisableReason(event.target.value)}
              className="input min-h-[5.5rem]"
              placeholder="原因，必填"
            />
          </div>
        </Modal>
      ) : null}

      {auditUser ? (
        <Modal
          isOpen={Boolean(auditUser)}
          title="用户审计详情"
          description={auditUser.email || auditUser.principal_id}
          size="xl"
          onClose={() => {
            setAuditUser(null);
            setAuditDetail(null);
            setAuditError(null);
          }}
          footer={
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setAuditUser(null);
                setAuditDetail(null);
                setAuditError(null);
              }}
            >
              关闭
            </button>
          }
        >
          {auditLoading ? (
            <LoadingFallback />
          ) : auditError ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/25 dark:text-rose-200">
              {auditError}
            </div>
          ) : (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ['事件数', String(auditDetail?.summary?.events || 0)],
                  ['注册事件', String(auditDetail?.summary?.registration_events || 0)],
                  ['禁用事件', String(auditDetail?.summary?.disable_events || 0)],
                  ['成功', String(auditDetail?.summary?.succeeded || 0)],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45"
                  >
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                      {label}
                    </div>
                    <div className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{value}</div>
                  </div>
                ))}
              </div>

              {auditDetail?.summary?.latest_disable_reason ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/25 dark:text-amber-200">
                  最近禁用原因：{auditDetail.summary.latest_disable_reason}
                </div>
              ) : null}

              <div className="space-y-3">
                {(auditDetail?.items || []).length === 0 ? (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-300">
                    暂无该用户的服务审计事件。
                  </div>
                ) : (
                  (auditDetail?.items || []).map((event) => {
                    const detail = payloadText(event.payload);
                    return (
                      <div
                        key={event.event_id}
                        className="rounded-2xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45"
                      >
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <div className="font-semibold text-slate-950 dark:text-white">
                              {auditEventLabel(event.event_kind)}
                            </div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {dateLabel(event.created_at)} · {event.actor_kind || 'unknown'} · {event.actor_ref || '无操作人'}
                            </div>
                          </div>
                          <BackofficeStatusBadge
                            label={event.outcome || 'unknown'}
                            status={event.outcome || 'inactive'}
                          />
                        </div>
                        {detail ? (
                          <div className="mt-3 text-sm text-slate-700 dark:text-slate-200">{detail}</div>
                        ) : null}
                        <div className="mt-3 grid gap-2 text-xs text-slate-500 dark:text-slate-400 sm:grid-cols-2">
                          <div>scope：{event.scope_kind || '-'} / {event.scope_id || '-'}</div>
                          <div>trace：{event.trace_id || '-'}</div>
                          <div>path：{event.method || 'GET'} {event.path || '-'}</div>
                          <div>idempotency：{event.idempotency_key || '-'}</div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </Modal>
      ) : null}
    </BackofficePageStack>
  );
}
