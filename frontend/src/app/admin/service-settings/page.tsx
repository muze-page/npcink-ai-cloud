'use client';

import React, { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';

type SettingStatus = 'ready' | 'disabled' | 'missing_config' | 'error' | string;
type ServiceSettingsTab = 'login' | 'email';
type BackendPayload = Record<string, unknown> | string | null;

type ServiceSetting = {
  setting_id: string;
  enabled: boolean;
  configured: boolean;
  status: SettingStatus;
  config: Record<string, unknown>;
  secrets: Record<string, { configured: boolean; display: string }>;
  last_tested_at: string;
  last_error_code: string;
  last_error_message: string;
};

type ServiceSettingsData = {
  settings: {
    portal_public: ServiceSetting;
    qq_login: ServiceSetting;
    portal_email: ServiceSetting;
  };
};

type PortalPublicForm = {
  enabled: boolean;
  public_base_url: string;
};

type QQForm = {
  enabled: boolean;
  client_id: string;
  client_secret: string;
};

type EmailForm = {
  enabled: boolean;
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_username_same_as_from_email: boolean;
  smtp_password: string;
  smtp_use_ssl: boolean;
  smtp_use_starttls: boolean;
  smtp_timeout_seconds: string;
  from_email: string;
  from_name: string;
  reply_to: string;
};

function stringValue(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function statusLabel(status: SettingStatus): string {
  if (status === 'ready') return '已就绪';
  if (status === 'disabled') return '已停用';
  if (status === 'error') return '异常';
  return '未配置';
}

function statusTone(status: SettingStatus): string {
  if (status === 'ready') return 'text-emerald-700 dark:text-emerald-300';
  if (status === 'error') return 'text-rose-700 dark:text-rose-300';
  if (status === 'disabled') return 'text-slate-500 dark:text-slate-400';
  return 'text-amber-700 dark:text-amber-300';
}

function fieldClassName(): string {
  return 'mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-white dark:focus:border-blue-500 dark:focus:ring-blue-950 dark:disabled:bg-slate-900';
}

function checkboxClassName(): string {
  return 'h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-950';
}

function switchButtonClassName(checked: boolean): string {
  return `relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-60 dark:focus:ring-blue-950 ${
    checked
      ? 'border-blue-600 bg-blue-600'
      : 'border-slate-300 bg-slate-200 dark:border-slate-700 dark:bg-slate-800'
  }`;
}

function switchKnobClassName(checked: boolean): string {
  return `inline-block h-5 w-5 rounded-full bg-white shadow-sm transition ${
    checked ? 'translate-x-5' : 'translate-x-0.5'
  }`;
}

function labelClassName(): string {
  return 'text-sm font-medium text-slate-700 dark:text-slate-200';
}

function buildQqRedirectUri(publicBaseUrl: string): string {
  const raw = publicBaseUrl.trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    return `${parsed.protocol}//${parsed.host}/open/auth/qq/callback`;
  } catch {
    return '';
  }
}

function payloadRecord(payload: BackendPayload): Record<string, unknown> | null {
  return payload && typeof payload === 'object' ? payload : null;
}

function serviceSettingsErrorMessage(
  record: Record<string, unknown>,
  fallback: string
): string {
  const errorCode = String(record.error_code || '').trim();
  const rawMessage = String(record.message || '').trim();
  if (errorCode === 'service_settings.email_delivery_failed') {
    if (/Authentication failure|authentication failed|auth/i.test(rawMessage)) {
      return 'SMTP 服务器拒绝认证。请检查 SMTP 用户名、密码或授权码是否正确，并确认发件邮箱已开通 SMTP 服务。';
    }
    if (/timed out|timeout/i.test(rawMessage)) {
      return '连接 SMTP 服务器超时。请检查 SMTP 服务器、端口、SSL/STARTTLS 方式以及网络连通性。';
    }
    if (/Name or service not known|getaddrinfo|ENOTFOUND/i.test(rawMessage)) {
      return '无法解析 SMTP 服务器地址。请检查 SMTP 服务器域名是否正确。';
    }
    return rawMessage
      ? `测试邮件发送失败：${rawMessage}`
      : '测试邮件发送失败。请检查 SMTP 服务器、端口、认证信息和加密方式。';
  }
  if (errorCode === 'service_settings.email_tls_mode_invalid') {
    return 'SMTP 加密方式不能同时启用 SSL 和 STARTTLS。465 端口通常只勾选 SSL；587 端口通常只勾选 STARTTLS。';
  }
  if (errorCode === 'service_settings.email_password_required') {
    return '已填写 SMTP 用户名时必须填写 SMTP 密码；如果之前已保存密码，密码框可留空。';
  }
  if (errorCode === 'service_settings.email_username_required') {
    return '已填写 SMTP 密码时必须填写 SMTP 用户名。';
  }
  if (errorCode === 'service_settings.email_smtp_host_required') {
    return '请填写 SMTP 服务器。';
  }
  if (errorCode === 'service_settings.email_from_email_invalid') {
    return '请填写有效的发件邮箱。';
  }
  return resolveUiErrorMessage(rawMessage, fallback);
}

async function readBackendPayload(response: Response): Promise<BackendPayload> {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  const text = await response.text().catch(() => '');
  return text.trim() || null;
}

function requestErrorMessage(
  response: Response,
  payload: BackendPayload,
  fallback: string
): string {
  const record = payloadRecord(payload);
  if (record) {
    const message = serviceSettingsErrorMessage(record, fallback);
    const errorCode = String(record.error_code || '').trim();
    if (errorCode.startsWith('service_settings.')) {
      return response.status >= 500 ? `${message}（HTTP ${response.status}）。` : message;
    }
    if (response.status >= 500) {
      return `${message}（HTTP ${response.status}）。请确认数据库迁移已执行，并查看 API 日志。`;
    }
    return message;
  }

  const text = typeof payload === 'string' ? payload : '';
  if (response.status >= 500) {
    const detail = text ? `：${text.slice(0, 120)}` : '';
    return `${fallback}：后端返回 ${response.status}${detail}。请确认数据库迁移已执行，并查看 API 日志。`;
  }
  if (text) {
    return `${fallback}：${text}`;
  }
  return `${fallback}（HTTP ${response.status}）。`;
}

function tabButtonClassName(active: boolean): string {
  return `rounded-[1rem] px-4 py-3 text-left transition ${
    active
      ? 'bg-slate-950 text-white shadow-sm dark:bg-white dark:text-slate-950'
      : 'text-slate-600 hover:bg-white/75 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900/70 dark:hover:text-white'
  }`;
}

export default function AdminServiceSettingsPage() {
  const { t } = useLocale();
  const [activeTab, setActiveTab] = useState<ServiceSettingsTab>('login');
  const [data, setData] = useState<ServiceSettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [emailTestRecipient, setEmailTestRecipient] = useState('');

  const [portalPublicForm, setPortalPublicForm] = useState<PortalPublicForm>({
    enabled: true,
    public_base_url: '',
  });
  const [qqForm, setQqForm] = useState<QQForm>({
    enabled: true,
    client_id: '',
    client_secret: '',
  });
  const [emailForm, setEmailForm] = useState<EmailForm>({
    enabled: true,
    smtp_host: '',
    smtp_port: '465',
    smtp_username: '',
    smtp_username_same_as_from_email: false,
    smtp_password: '',
    smtp_use_ssl: true,
    smtp_use_starttls: false,
    smtp_timeout_seconds: '20',
    from_email: '',
    from_name: '',
    reply_to: '',
  });

  async function loadSettings() {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/service-settings', { credentials: 'include' });
      const payload = await readBackendPayload(response);
      if (!response.ok) {
        throw new Error(requestErrorMessage(response, payload, '加载服务配置失败'));
      }
      const record = payloadRecord(payload);
      const nextData = record?.data as ServiceSettingsData | undefined;
      if (!nextData?.settings) {
        throw new Error('服务配置响应格式不正确。');
      }
      setData(nextData);
      const portalPublic = nextData.settings.portal_public;
      const qq = nextData.settings.qq_login;
      const email = nextData.settings.portal_email;
      const emailSmtpUsername = stringValue(email.config.smtp_username);
      const emailFromAddress = stringValue(email.config.from_email);
      const emailUsernameSameAsFromEmail =
        Boolean(emailSmtpUsername && emailFromAddress) &&
        emailSmtpUsername.toLowerCase() === emailFromAddress.toLowerCase();
      setPortalPublicForm({
        enabled: portalPublic.enabled,
        public_base_url: stringValue(portalPublic.config.public_base_url),
      });
      setQqForm({
        enabled: qq.enabled,
        client_id: stringValue(qq.config.client_id),
        client_secret: '',
      });
      setEmailForm({
        enabled: email.enabled,
        smtp_host: stringValue(email.config.smtp_host),
        smtp_port: stringValue(email.config.smtp_port) || '465',
        smtp_username: emailUsernameSameAsFromEmail ? emailFromAddress : emailSmtpUsername,
        smtp_username_same_as_from_email: emailUsernameSameAsFromEmail,
        smtp_password: '',
        smtp_use_ssl: boolValue(email.config.smtp_use_ssl, true),
        smtp_use_starttls: boolValue(email.config.smtp_use_starttls, false),
        smtp_timeout_seconds: stringValue(email.config.smtp_timeout_seconds) || '20',
        from_email: stringValue(email.config.from_email),
        from_name: stringValue(email.config.from_name),
        reply_to: stringValue(email.config.reply_to),
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '加载服务配置失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSettings();
  }, []);

  const metrics = useMemo(() => {
    const settings = data?.settings;
    return [
      {
        label: '公开地址',
        value: statusLabel(settings?.portal_public.status || 'missing_config'),
        toneClassName: statusTone(settings?.portal_public.status || 'missing_config'),
        size: 'compact' as const,
      },
      {
        label: 'QQ 登录',
        value: statusLabel(settings?.qq_login.status || 'missing_config'),
        toneClassName: statusTone(settings?.qq_login.status || 'missing_config'),
        size: 'compact' as const,
      },
      {
        label: '邮件发送',
        value: statusLabel(settings?.portal_email.status || 'missing_config'),
        toneClassName: statusTone(settings?.portal_email.status || 'missing_config'),
        size: 'compact' as const,
      },
    ];
  }, [data]);

  const qqRedirectUri = useMemo(() => {
    return buildQqRedirectUri(portalPublicForm.public_base_url);
  }, [portalPublicForm.public_base_url]);

  async function copyQqRedirectUri() {
    if (!qqRedirectUri) {
      setError('请先填写有效的公开基础 URL。');
      setNotice('');
      return;
    }
    try {
      await navigator.clipboard.writeText(qqRedirectUri);
      setError('');
      setNotice('QQ 回调地址已复制。');
    } catch {
      setError('当前浏览器无法自动复制，请手动复制回调地址。');
      setNotice('');
    }
  }

  async function saveJson(
    path: string,
    body: Record<string, unknown>,
    savingKey: string,
    successMessage: string
  ) {
    setSaving(savingKey);
    setError('');
    setNotice('');
    try {
      const response = await fetch(path, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await readBackendPayload(response);
      if (!response.ok) {
        throw new Error(requestErrorMessage(response, payload, '保存服务配置失败'));
      }
      setNotice(successMessage);
      await loadSettings();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存服务配置失败');
    } finally {
      setSaving('');
    }
  }

  async function postJson(
    path: string,
    body: Record<string, unknown>,
    savingKey: string,
    successMessage: string
  ) {
    setSaving(savingKey);
    setError('');
    setNotice('');
    try {
      const response = await fetch(path, {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await readBackendPayload(response);
      if (!response.ok) {
        throw new Error(requestErrorMessage(response, payload, '测试服务配置失败'));
      }
      setNotice(successMessage);
      await loadSettings();
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : '测试服务配置失败');
    } finally {
      setSaving('');
    }
  }

  function submitPortalPublic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void saveJson(
      '/api/admin/service-settings/portal-public',
      portalPublicForm,
      'portal-public',
      '公开访问地址已保存。'
    );
  }

  function submitQq(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!qqRedirectUri) {
      setNotice('');
      setError('请先填写有效的公开基础 URL，QQ 回调地址会自动生成。');
      return;
    }
    const payload: Record<string, unknown> = {
      enabled: qqForm.enabled,
      client_id: qqForm.client_id,
      redirect_uri: qqRedirectUri,
      scope: 'get_user_info',
      timeout_seconds: 10,
    };
    if (qqForm.client_secret) {
      payload.client_secret = qqForm.client_secret;
    }
    void saveJson('/api/admin/service-settings/qq-login', payload, 'qq-login', 'QQ 登录配置已保存。');
  }

  function submitEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (emailForm.smtp_use_ssl && emailForm.smtp_use_starttls) {
      setNotice('');
      setError('SMTP 加密方式不能同时启用 SSL 和 STARTTLS。465 端口通常只勾选 SSL；587 端口通常只勾选 STARTTLS。');
      return;
    }
    const payload: Record<string, unknown> = {
      enabled: emailForm.enabled,
      smtp_host: emailForm.smtp_host,
      smtp_port: Number(emailForm.smtp_port || 465),
      smtp_username: emailForm.smtp_username_same_as_from_email
        ? emailForm.from_email
        : emailForm.smtp_username,
      smtp_use_ssl: emailForm.smtp_use_ssl,
      smtp_use_starttls: emailForm.smtp_use_starttls,
      smtp_timeout_seconds: Number(emailForm.smtp_timeout_seconds || 20),
      from_email: emailForm.from_email,
      from_name: emailForm.from_name,
      reply_to: emailForm.reply_to,
    };
    if (emailForm.smtp_password) {
      payload.smtp_password = emailForm.smtp_password;
    }
    void saveJson('/api/admin/service-settings/email', payload, 'email', '邮件配置已保存。');
  }

  const secretConfigured = {
    qq: Boolean(data?.settings.qq_login.secrets.client_secret?.configured),
    email: Boolean(data?.settings.portal_email.secrets.smtp_password?.configured),
  };

  const tabs: Array<{ id: ServiceSettingsTab; label: string; description: string }> = [
    {
      id: 'login',
      label: '登录配置',
      description: '公开地址和 QQ 快捷登录',
    },
    {
      id: 'email',
      label: '邮件配置',
      description: 'SMTP 和测试邮件',
    },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, '运营界面')}
        title={t('admin.service_settings_title', {}, '服务配置')}
        description={t(
          'admin.service_settings_desc',
          {},
          '配置 Cloud 自有的 Portal 登录、QQ 快捷登录和邮件发送。配置保存在 Cloud 运行时存储中，不再读取 .env 回退。'
        )}
        aside={(
          <div className="w-full xl:w-[34rem]">
            <BackofficeMetricStrip items={metrics} columnsClassName="md:grid-cols-3 xl:grid-cols-3" />
          </div>
        )}
      />

      {error ? (
        <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
          {error}
        </BackofficeStackCard>
      ) : null}
      {notice ? (
        <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">
          {notice}
        </BackofficeStackCard>
      ) : null}

      <BackofficeSectionPanel className="p-2 md:p-2">
        <div role="tablist" aria-label="服务配置分类" className="grid gap-2 md:grid-cols-2">
          {tabs.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={`service-settings-${tab.id}`}
                className={tabButtonClassName(active)}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="block text-sm font-semibold">{tab.label}</span>
                <span className={`mt-1 block text-xs ${active ? 'text-white/70 dark:text-slate-700' : 'text-slate-500 dark:text-slate-400'}`}>
                  {tab.description}
                </span>
              </button>
            );
          })}
        </div>
      </BackofficeSectionPanel>

      {activeTab === 'login' ? (
        <BackofficeSectionPanel>
          <div id="service-settings-login" className="space-y-8" role="tabpanel">
            <section className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                Portal URL
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                门户基础地址
              </h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                用于生成 QQ、微信登录和支付通知等公开回调地址。
              </p>
            </div>
            <form className="grid gap-4 lg:grid-cols-[1fr_auto]" onSubmit={submitPortalPublic}>
              <label className={labelClassName()}>
                基础 URL
                <input
                  className={fieldClassName()}
                  value={portalPublicForm.public_base_url}
                  onChange={(event) => setPortalPublicForm((current) => ({ ...current, public_base_url: event.target.value }))}
                  placeholder="https://cloud.example.com"
                  disabled={loading}
                />
              </label>
              <div className="flex items-end gap-3">
                <div className="mb-2 inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                  <button
                    type="button"
                    role="switch"
                    aria-label="启用公开访问地址"
                    aria-checked={portalPublicForm.enabled}
                    className={switchButtonClassName(portalPublicForm.enabled)}
                    disabled={loading}
                    onClick={() => setPortalPublicForm((current) => ({ ...current, enabled: !current.enabled }))}
                  >
                    <span className={switchKnobClassName(portalPublicForm.enabled)} />
                  </button>
                  门户入口启用
                </div>
                <button type="submit" className="btn btn-primary" disabled={saving === 'portal-public'}>
                  {saving === 'portal-public' ? '保存中' : '保存基础地址'}
                </button>
              </div>
            </form>
            </section>

            <section className="space-y-4 border-t border-slate-200 pt-6 dark:border-slate-800">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                QQ OAuth
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">QQ 快捷登录</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                回调地址由门户基础地址自动生成；这里仅保存 QQ App 凭据和登录开关。
              </p>
            </div>
            <form className="grid gap-4 lg:grid-cols-2" onSubmit={submitQq}>
              <label className={labelClassName()}>
                App ID
                <input className={fieldClassName()} value={qqForm.client_id} disabled={loading} onChange={(event) => setQqForm((current) => ({ ...current, client_id: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                App Secret {secretConfigured.qq ? '（已配置）' : '（未配置）'}
                <input className={fieldClassName()} type="password" value={qqForm.client_secret} disabled={loading} onChange={(event) => setQqForm((current) => ({ ...current, client_secret: event.target.value }))} placeholder={secretConfigured.qq ? '留空则保留当前密钥' : '必填'} />
              </label>
              <div className="lg:col-span-2">
                <div className={labelClassName()}>
                  回调地址
                  <div className="mt-1 grid gap-2 lg:grid-cols-[1fr_auto]">
                    <input
                      className={fieldClassName()}
                      value={qqRedirectUri}
                      readOnly
                      disabled={loading}
                      placeholder="填写公开基础 URL 后自动生成"
                    />
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={!qqRedirectUri}
                      onClick={() => void copyQqRedirectUri()}
                    >
                      复制
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex items-end justify-between gap-3 lg:col-span-2">
                <div className="mb-2 inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                  <button
                    type="button"
                    role="switch"
                    aria-label="启用 QQ 快捷登录"
                    aria-checked={qqForm.enabled}
                    className={switchButtonClassName(qqForm.enabled)}
                    disabled={loading}
                    onClick={() => setQqForm((current) => ({ ...current, enabled: !current.enabled }))}
                  >
                    <span className={switchKnobClassName(qqForm.enabled)} />
                  </button>
                  启用 QQ 登录
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn btn-secondary" disabled={saving === 'qq-test'} onClick={() => postJson('/api/admin/service-settings/qq-login/test', {}, 'qq-test', 'QQ 登录配置检查完成。')}>
                    检查 QQ 配置
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={saving === 'qq-login'}>
                    {saving === 'qq-login' ? '保存中' : '保存 QQ 配置'}
                  </button>
                </div>
              </div>
            </form>
            </section>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeTab === 'email' ? (
        <BackofficeSectionPanel>
          <div id="service-settings-email" className="space-y-8" role="tabpanel">
            <section className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                SMTP
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">邮件发送</h2>
            </div>
            <form className="grid gap-4 lg:grid-cols-2" onSubmit={submitEmail}>
              <label className={labelClassName()}>
                SMTP 服务器
                <input className={fieldClassName()} value={emailForm.smtp_host} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_host: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                SMTP 端口
                <input className={fieldClassName()} value={emailForm.smtp_port} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_port: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                <span className="flex items-center justify-between gap-3">
                  <span>SMTP 用户名</span>
                  <span className="inline-flex items-center gap-2 text-xs font-normal text-slate-500 dark:text-slate-400">
                    <input
                      type="checkbox"
                      className={checkboxClassName()}
                      checked={emailForm.smtp_username_same_as_from_email}
                      disabled={loading}
                      onChange={(event) =>
                        setEmailForm((current) => ({
                          ...current,
                          smtp_username_same_as_from_email: event.target.checked,
                          smtp_username: event.target.checked
                            ? current.from_email
                            : current.smtp_username,
                        }))
                      }
                    />
                    同发件邮箱
                  </span>
                </span>
                <input
                  className={fieldClassName()}
                  value={
                    emailForm.smtp_username_same_as_from_email
                      ? emailForm.from_email
                      : emailForm.smtp_username
                  }
                  disabled={loading || emailForm.smtp_username_same_as_from_email}
                  onChange={(event) =>
                    setEmailForm((current) => ({
                      ...current,
                      smtp_username: event.target.value,
                    }))
                  }
                  placeholder={
                    emailForm.smtp_username_same_as_from_email
                      ? '自动使用发件邮箱'
                      : '通常填写完整邮箱地址'
                  }
                />
              </label>
              <label className={labelClassName()}>
                SMTP 密码 {secretConfigured.email ? '（已配置）' : '（未配置）'}
                <input className={fieldClassName()} type="password" value={emailForm.smtp_password} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_password: event.target.value }))} placeholder={secretConfigured.email ? '留空则保留当前密码' : '设置用户名时必填'} />
              </label>
              <label className={labelClassName()}>
                发件邮箱
                <input
                  className={fieldClassName()}
                  value={emailForm.from_email}
                  disabled={loading}
                  onChange={(event) =>
                    setEmailForm((current) => ({
                      ...current,
                      from_email: event.target.value,
                      smtp_username: current.smtp_username_same_as_from_email
                        ? event.target.value
                        : current.smtp_username,
                    }))
                  }
                />
              </label>
              <label className={labelClassName()}>
                发件人名称
                <input className={fieldClassName()} value={emailForm.from_name} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, from_name: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                回复邮箱
                <input className={fieldClassName()} value={emailForm.reply_to} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, reply_to: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                超时时间（秒）
                <input className={fieldClassName()} value={emailForm.smtp_timeout_seconds} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_timeout_seconds: event.target.value }))} />
              </label>
              <div className="flex flex-wrap items-center gap-5 text-sm text-slate-700 dark:text-slate-200">
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" className={checkboxClassName()} checked={emailForm.smtp_use_ssl} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_use_ssl: event.target.checked, smtp_use_starttls: event.target.checked ? false : current.smtp_use_starttls }))} />
                  SSL
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" className={checkboxClassName()} checked={emailForm.smtp_use_starttls} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_use_starttls: event.target.checked, smtp_use_ssl: event.target.checked ? false : current.smtp_use_ssl }))} />
                  STARTTLS
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" className={checkboxClassName()} checked={emailForm.enabled} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, enabled: event.target.checked }))} />
                  启用
                </label>
              </div>
              <div className="flex justify-end">
                <button type="submit" className="btn btn-primary" disabled={saving === 'email'}>
                  {saving === 'email' ? '保存中' : '保存'}
                </button>
              </div>
            </form>
            </section>

            <section className="grid gap-3 border-t border-slate-200 pt-6 dark:border-slate-800 lg:grid-cols-[1fr_auto]">
            <label className={labelClassName()}>
              测试收件人
              <input className={fieldClassName()} value={emailTestRecipient} onChange={(event) => setEmailTestRecipient(event.target.value)} placeholder="operator@example.com" />
            </label>
            <div className="flex items-end justify-end">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving === 'email-test' || !emailTestRecipient}
                onClick={() => postJson('/api/admin/service-settings/email/test', { recipient_email: emailTestRecipient }, 'email-test', '测试邮件已发送。')}
              >
                发送测试邮件
              </button>
            </div>
            </section>
          </div>
        </BackofficeSectionPanel>
      ) : null}
    </BackofficePageStack>
  );
}
