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
import { ConfirmModal } from '@/components/ui/Modal';
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
                      <button
                        type="button"
                        className={cn('btn btn-secondary', user.status === 'disabled' && 'opacity-60')}
                        disabled={user.status === 'disabled' || savingPrincipalId === user.principal_id}
                        onClick={() => setPendingUser(user)}
                      >
                        {savingPrincipalId === user.principal_id ? '处理中' : '禁用'}
                      </button>
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
    </BackofficePageStack>
  );
}
