'use client';

import React, { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
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
type ServiceSettingsTab = 'login' | 'email' | 'payment';
type BackendPayload = Record<string, unknown> | string | null;
type Translator = (key: string, params?: Record<string, string>, fallback?: string) => string;

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
    alipay_payment: ServiceSetting;
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

type AlipayForm = {
  enabled: boolean;
  app_id: string;
  gateway_url: string;
  notify_url: string;
  return_url: string;
  private_key: string;
  public_key: string;
};

function stringValue(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function statusLabel(status: SettingStatus, t: Translator): string {
  if (status === 'ready') return t('admin.service_settings.status_ready', {}, 'Ready');
  if (status === 'disabled') return t('admin.service_settings.status_disabled', {}, 'Disabled');
  if (status === 'error') return t('admin.service_settings.status_error', {}, 'Error');
  return t('admin.service_settings.status_missing_config', {}, 'Not configured');
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

function buildAlipayNotifyUrl(publicBaseUrl: string): string {
  const raw = publicBaseUrl.trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    return `${parsed.protocol}//${parsed.host}/open/payments/alipay/notify`;
  } catch {
    return '';
  }
}

function buildAlipayReturnUrl(publicBaseUrl: string): string {
  const raw = publicBaseUrl.trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    return `${parsed.protocol}//${parsed.host}/open/payments/alipay/return`;
  } catch {
    return '';
  }
}

function payloadRecord(payload: BackendPayload): Record<string, unknown> | null {
  return payload && typeof payload === 'object' ? payload : null;
}

function serviceSettingsErrorMessage(
  record: Record<string, unknown>,
  fallback: string,
  t: Translator
): string {
  const errorCode = String(record.error_code || '').trim();
  const rawMessage = String(record.message || '').trim();
  if (errorCode === 'service_settings.email_delivery_failed') {
    if (/Authentication failure|authentication failed|auth/i.test(rawMessage)) {
      return t('admin.service_settings.error_email_auth_failed', {}, 'SMTP 服务器拒绝认证。请检查 SMTP 用户名、密码或应用专用密码，并确认发件邮箱已启用 SMTP。');
    }
    if (/timed out|timeout/i.test(rawMessage)) {
      return t('admin.service_settings.error_email_timeout', {}, 'The SMTP connection timed out. Check the SMTP host, port, SSL/STARTTLS mode, and network connectivity.');
    }
    if (/Name or service not known|getaddrinfo|ENOTFOUND/i.test(rawMessage)) {
      return t('admin.service_settings.error_email_host_lookup', {}, 'The SMTP host could not be resolved. Check the SMTP server domain.');
    }
    return rawMessage
      ? t('admin.service_settings.error_email_delivery_detail', { message: rawMessage }, 'Test email failed: {{message}}')
      : t('admin.service_settings.error_email_delivery_failed', {}, 'Test email failed. Check the SMTP host, port, authentication, and encryption mode.');
  }
  if (errorCode === 'service_settings.email_tls_mode_invalid') {
    return t('admin.service_settings.error_tls_mode_invalid', {}, 'SMTP 加密方式不能同时启用 SSL 和 STARTTLS。465 端口通常只使用 SSL，587 端口通常只使用 STARTTLS。');
  }
  if (errorCode === 'service_settings.email_password_required') {
    return t('admin.service_settings.error_email_password_required', {}, 'SMTP password is required when an SMTP username is set. Leave the password field empty only if a password was already saved.');
  }
  if (errorCode === 'service_settings.email_username_required') {
    return t('admin.service_settings.error_email_username_required', {}, 'SMTP username is required when an SMTP password is set.');
  }
  if (errorCode === 'service_settings.email_smtp_host_required') {
    return t('admin.service_settings.error_email_smtp_host_required', {}, 'Enter an SMTP server.');
  }
  if (errorCode === 'service_settings.email_from_email_invalid') {
    return t('admin.service_settings.error_email_from_invalid', {}, 'Enter a valid sender email address.');
  }
  if (errorCode === 'service_settings.alipay_private_key_required') {
    return t('admin.service_settings.error_alipay_private_key_required', {}, '请输入支付宝应用私钥。');
  }
  if (errorCode === 'service_settings.alipay_public_key_required') {
    return t('admin.service_settings.error_alipay_public_key_required', {}, '请输入支付宝公钥。');
  }
  if (errorCode === 'service_settings.alipay_notify_url_invalid') {
    return t('admin.service_settings.error_alipay_notify_url_invalid', {}, '支付宝异步通知地址必须来自门户基础地址，并使用 /open/payments/alipay/notify。');
  }
  if (errorCode === 'service_settings.alipay_return_url_invalid') {
    return t('admin.service_settings.error_alipay_return_url_invalid', {}, '支付宝同步返回地址必须来自门户基础地址，并使用 /open/payments/alipay/return。');
  }
  if (errorCode === 'service_settings.alipay_config_invalid') {
    return rawMessage
      ? t('admin.service_settings.error_alipay_config_detail', { message: rawMessage }, '支付宝配置检查失败：{{message}}')
      : t('admin.service_settings.error_alipay_config_invalid', {}, '支付宝配置检查失败。请检查 App ID、应用私钥、支付宝公钥。');
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
  fallback: string,
  t: Translator
): string {
  const record = payloadRecord(payload);
  if (record) {
    const message = serviceSettingsErrorMessage(record, fallback, t);
    const errorCode = String(record.error_code || '').trim();
    if (errorCode.startsWith('service_settings.')) {
      return response.status >= 500
        ? t('admin.service_settings.error_http_suffix', { message, status: String(response.status) }, '{{message}} (HTTP {{status}}).')
        : message;
    }
    if (response.status >= 500) {
      return t('admin.service_settings.error_http_migration_hint', { message, status: String(response.status) }, '{{message}}（HTTP {{status}}）。请确认数据库迁移已执行，并查看 API 日志。');
    }
    return message;
  }

  const text = typeof payload === 'string' ? payload : '';
  if (response.status >= 500) {
    const detail = text ? `：${text.slice(0, 120)}` : '';
    return t('admin.service_settings.error_backend_status', { fallback, status: String(response.status), detail }, '{{fallback}}：后端返回 {{status}}{{detail}}。请确认数据库迁移已执行，并查看 API 日志。');
  }
  if (text) {
    return t('admin.service_settings.error_with_detail', { fallback, detail: text }, '{{fallback}}: {{detail}}');
  }
  return t('admin.service_settings.error_http_suffix', { message: fallback, status: String(response.status) }, '{{message}} (HTTP {{status}}).');
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
  const [alipayForm, setAlipayForm] = useState<AlipayForm>({
    enabled: false,
    app_id: '',
    gateway_url: 'https://openapi.alipay.com/gateway.do',
    notify_url: '',
    return_url: '',
    private_key: '',
    public_key: '',
  });

  const loadSettings = useCallback(async function loadSettings() {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/service-settings', { credentials: 'include' });
      const payload = await readBackendPayload(response);
      if (!response.ok) {
        throw new Error(requestErrorMessage(response, payload, t('admin.service_settings.load_failed', {}, 'Failed to load service settings.'), t));
      }
      const record = payloadRecord(payload);
      const nextData = record?.data as ServiceSettingsData | undefined;
      if (!nextData?.settings) {
        throw new Error(t('admin.service_settings.invalid_response', {}, 'Service settings response is invalid.'));
      }
      setData(nextData);
      const portalPublic = nextData.settings.portal_public;
      const qq = nextData.settings.qq_login;
      const email = nextData.settings.portal_email;
      const alipay = nextData.settings.alipay_payment;
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
      setAlipayForm({
        enabled: alipay.enabled,
        app_id: stringValue(alipay.config.app_id),
        gateway_url: stringValue(alipay.config.gateway_url) || 'https://openapi.alipay.com/gateway.do',
        notify_url: stringValue(alipay.config.notify_url),
        return_url: stringValue(alipay.config.return_url),
        private_key: '',
        public_key: '',
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('admin.service_settings.load_failed', {}, 'Failed to load service settings.'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const metrics = useMemo(() => {
    const settings = data?.settings;
    return [
      {
        label: t('admin.service_settings.metric_public_url', {}, 'Public URL'),
        value: statusLabel(settings?.portal_public.status || 'missing_config', t),
        toneClassName: statusTone(settings?.portal_public.status || 'missing_config'),
        size: 'compact' as const,
      },
      {
        label: t('admin.service_settings.metric_qq_login', {}, 'QQ login'),
        value: statusLabel(settings?.qq_login.status || 'missing_config', t),
        toneClassName: statusTone(settings?.qq_login.status || 'missing_config'),
        size: 'compact' as const,
      },
      {
        label: t('admin.service_settings.metric_email', {}, 'Email delivery'),
        value: statusLabel(settings?.portal_email.status || 'missing_config', t),
        toneClassName: statusTone(settings?.portal_email.status || 'missing_config'),
        size: 'compact' as const,
      },
      {
        label: t('admin.service_settings.metric_payment', {}, 'Payment'),
        value: statusLabel(settings?.alipay_payment.status || 'missing_config', t),
        toneClassName: statusTone(settings?.alipay_payment.status || 'missing_config'),
        size: 'compact' as const,
      },
    ];
  }, [data, t]);

  const qqRedirectUri = useMemo(() => {
    return buildQqRedirectUri(portalPublicForm.public_base_url);
  }, [portalPublicForm.public_base_url]);

  const defaultAlipayNotifyUrl = useMemo(() => {
    return buildAlipayNotifyUrl(portalPublicForm.public_base_url);
  }, [portalPublicForm.public_base_url]);

  const defaultAlipayReturnUrl = useMemo(() => {
    return buildAlipayReturnUrl(portalPublicForm.public_base_url);
  }, [portalPublicForm.public_base_url]);

  const resolvedAlipayNotifyUrl = alipayForm.notify_url || defaultAlipayNotifyUrl;
  const resolvedAlipayReturnUrl = alipayForm.return_url || defaultAlipayReturnUrl;

  async function copyQqRedirectUri() {
    if (!qqRedirectUri) {
      setError(t('admin.service_settings.public_base_url_required', {}, 'Enter a valid public base URL first.'));
      setNotice('');
      return;
    }
    try {
      await navigator.clipboard.writeText(qqRedirectUri);
      setError('');
      setNotice(t('admin.service_settings.qq_redirect_copied', {}, 'QQ 回调地址已复制。'));
    } catch {
      setError(t('admin.service_settings.copy_failed', {}, 'This browser could not copy automatically. Copy the redirect URL manually.'));
      setNotice('');
    }
  }

  async function copyText(value: string, successMessage: string) {
    if (!value) {
      setError(t('admin.service_settings.copy_empty', {}, 'Nothing to copy yet.'));
      setNotice('');
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setError('');
      setNotice(successMessage);
    } catch {
      setError(t('admin.service_settings.copy_failed', {}, 'This browser could not copy automatically. Copy the value manually.'));
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
        throw new Error(requestErrorMessage(response, payload, t('admin.service_settings.save_failed', {}, 'Failed to save service settings.'), t));
      }
      setNotice(successMessage);
      await loadSettings();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t('admin.service_settings.save_failed', {}, 'Failed to save service settings.'));
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
        throw new Error(requestErrorMessage(response, payload, t('admin.service_settings.test_failed', {}, 'Failed to test service settings.'), t));
      }
      setNotice(successMessage);
      await loadSettings();
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : t('admin.service_settings.test_failed', {}, 'Failed to test service settings.'));
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
      t('admin.service_settings.public_url_saved', {}, 'Public URL saved.')
    );
  }

  function submitQq(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!qqRedirectUri) {
      setNotice('');
      setError(t('admin.service_settings.qq_redirect_requires_public_url', {}, 'Enter a valid public base URL first. The QQ redirect URL is generated automatically.'));
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
    void saveJson('/api/admin/service-settings/qq-login', payload, 'qq-login', t('admin.service_settings.qq_saved', {}, 'QQ login settings saved.'));
  }

  function submitEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (emailForm.smtp_use_ssl && emailForm.smtp_use_starttls) {
      setNotice('');
      setError(t('admin.service_settings.error_tls_mode_invalid', {}, 'SSL and STARTTLS cannot be enabled at the same time. Port 465 usually uses SSL only; port 587 usually uses STARTTLS only.'));
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
    void saveJson('/api/admin/service-settings/email', payload, 'email', t('admin.service_settings.email_saved', {}, 'Email settings saved.'));
  }

  function submitAlipay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (alipayForm.enabled && (!resolvedAlipayNotifyUrl || !resolvedAlipayReturnUrl)) {
      setNotice('');
      setError(t('admin.service_settings.alipay_requires_public_url', {}, '先保存门户基础地址，再保存支付宝配置。notify_url 和 return_url 会自动生成。'));
      return;
    }
    const payload: Record<string, unknown> = {
      enabled: alipayForm.enabled,
      app_id: alipayForm.app_id,
      gateway_url: alipayForm.gateway_url,
      notify_url: resolvedAlipayNotifyUrl,
      return_url: resolvedAlipayReturnUrl,
    };
    if (alipayForm.private_key) {
      payload.private_key = alipayForm.private_key;
    }
    if (alipayForm.public_key) {
      payload.public_key = alipayForm.public_key;
    }
    void saveJson('/api/admin/service-settings/alipay-payment', payload, 'alipay-payment', t('admin.service_settings.alipay_saved', {}, '支付宝支付配置已保存。'));
  }

  const secretConfigured = {
    qq: Boolean(data?.settings.qq_login.secrets.client_secret?.configured),
    email: Boolean(data?.settings.portal_email.secrets.smtp_password?.configured),
    alipayPrivateKey: Boolean(data?.settings.alipay_payment.secrets.private_key?.configured),
    alipayPublicKey: Boolean(data?.settings.alipay_payment.secrets.public_key?.configured),
  };

  const tabs: Array<{ id: ServiceSettingsTab; label: string; description: string }> = [
    {
      id: 'login',
      label: t('admin.service_settings.tab_login', {}, '登录配置'),
      description: t('admin.service_settings.tab_login_desc', {}, 'Public URL and QQ quick login'),
    },
    {
      id: 'email',
      label: t('admin.service_settings.tab_email', {}, '邮件配置'),
      description: t('admin.service_settings.tab_email_desc', {}, 'SMTP and test email'),
    },
    {
      id: 'payment',
      label: t('admin.service_settings.tab_payment', {}, '支付配置'),
      description: t('admin.service_settings.tab_payment_desc', {}, 'Alipay checkout callbacks'),
    },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.service_settings_title', {}, 'Service settings')}
        description={t(
          'admin.service_settings_desc',
          {},
          'Configure Cloud-owned Portal login, QQ quick login, email delivery, and payment. Values are stored in Cloud runtime storage; .env fallback is no longer read.'
        )}
        descriptionDisplay="hint"
        aside={(
          <div className="w-full xl:w-[34rem]">
            <BackofficeMetricStrip items={metrics} columnsClassName="md:grid-cols-4 xl:grid-cols-4" />
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
        <div role="tablist" aria-label={t('admin.service_settings.tablist_label', {}, 'Service settings categories')} className="grid gap-2 md:grid-cols-3">
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
                {t('admin.service_settings.portal_public_title', {}, '门户基础地址')}
              </h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t('admin.service_settings.portal_public_desc', {}, 'Used to generate public callback URLs for QQ login, WeChat login, and payment notifications.')}
              </p>
            </div>
            <form className="grid gap-4 lg:grid-cols-[1fr_auto]" onSubmit={submitPortalPublic}>
              <label className={labelClassName()}>
                {t('admin.service_settings.base_url_label', {}, 'Base URL')}
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
                    aria-label={t('admin.service_settings.public_url_toggle_label', {}, 'Enable public URL')}
                    aria-checked={portalPublicForm.enabled}
                    className={switchButtonClassName(portalPublicForm.enabled)}
                    disabled={loading}
                    onClick={() => setPortalPublicForm((current) => ({ ...current, enabled: !current.enabled }))}
                  >
                    <span className={switchKnobClassName(portalPublicForm.enabled)} />
                  </button>
                  {t('admin.service_settings.portal_enabled_label', {}, 'Portal entry enabled')}
                </div>
                <button type="submit" className="btn btn-primary" disabled={saving === 'portal-public'}>
                  {saving === 'portal-public'
                    ? t('admin.service_settings.saving', {}, 'Saving')
                    : t('admin.service_settings.save_base_url', {}, '保存基础地址')}
                </button>
              </div>
            </form>
            </section>

            <section className="space-y-4 border-t border-slate-200 pt-6 dark:border-slate-800">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                QQ OAuth
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.service_settings.qq_title', {}, 'QQ 快捷登录')}</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t('admin.service_settings.qq_desc', {}, '回调地址由门户基础地址自动生成。这里仅保存 QQ 应用凭证和登录开关。')}
              </p>
            </div>
            <form className="grid gap-4 lg:grid-cols-2" onSubmit={submitQq}>
              <label className={labelClassName()}>
                App ID
                <input className={fieldClassName()} value={qqForm.client_id} disabled={loading} onChange={(event) => setQqForm((current) => ({ ...current, client_id: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                App Secret {secretConfigured.qq
                  ? t('admin.service_settings.secret_configured_suffix', {}, '(configured)')
                  : t('admin.service_settings.secret_missing_suffix', {}, '(not configured)')}
                <input className={fieldClassName()} type="password" value={qqForm.client_secret} disabled={loading} onChange={(event) => setQqForm((current) => ({ ...current, client_secret: event.target.value }))} placeholder={secretConfigured.qq ? t('admin.service_settings.qq_secret_keep_placeholder', {}, 'Leave empty to keep the current secret') : t('admin.service_settings.required_placeholder', {}, 'Required')} />
              </label>
              <div className="lg:col-span-2">
                <div className={labelClassName()}>
                  {t('admin.service_settings.redirect_uri_label', {}, 'Redirect URL')}
                  <div className="mt-1 grid gap-2 lg:grid-cols-[1fr_auto]">
                    <input
                      className={fieldClassName()}
                      value={qqRedirectUri}
                      readOnly
                      disabled={loading}
                      placeholder={t('admin.service_settings.redirect_uri_placeholder', {}, 'Generated after a public base URL is entered')}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={!qqRedirectUri}
                      onClick={() => void copyQqRedirectUri()}
                    >
                      {t('common.copy', {}, 'Copy')}
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex items-end justify-between gap-3 lg:col-span-2">
                <div className="mb-2 inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                  <button
                    type="button"
                    role="switch"
                    aria-label={t('admin.service_settings.qq_toggle_label', {}, '启用 QQ 快捷登录')}
                    aria-checked={qqForm.enabled}
                    className={switchButtonClassName(qqForm.enabled)}
                    disabled={loading}
                    onClick={() => setQqForm((current) => ({ ...current, enabled: !current.enabled }))}
                  >
                    <span className={switchKnobClassName(qqForm.enabled)} />
                  </button>
                  {t('admin.service_settings.qq_enabled_label', {}, '启用 QQ 登录')}
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn btn-secondary" disabled={saving === 'qq-test'} onClick={() => postJson('/api/admin/service-settings/qq-login/test', {}, 'qq-test', t('admin.service_settings.qq_test_done', {}, 'QQ login configuration check completed.'))}>
                    {t('admin.service_settings.check_qq', {}, 'Check QQ settings')}
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={saving === 'qq-login'}>
                    {saving === 'qq-login'
                      ? t('admin.service_settings.saving', {}, 'Saving')
                      : t('admin.service_settings.save_qq', {}, '保存 QQ 配置')}
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
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.service_settings.email_title', {}, 'Email delivery')}</h2>
            </div>
            <form className="grid gap-4 lg:grid-cols-2" onSubmit={submitEmail}>
              <label className={labelClassName()}>
                {t('admin.service_settings.smtp_host_label', {}, 'SMTP server')}
                <input className={fieldClassName()} value={emailForm.smtp_host} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_host: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                {t('admin.service_settings.smtp_port_label', {}, 'SMTP port')}
                <input className={fieldClassName()} value={emailForm.smtp_port} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_port: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                <span className="flex items-center justify-between gap-3">
                  <span>{t('admin.service_settings.smtp_username_label', {}, 'SMTP username')}</span>
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
                    {t('admin.service_settings.same_as_from_email', {}, '同发件邮箱')}
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
                      ? t('admin.service_settings.auto_from_email_placeholder', {}, 'Uses the sender email automatically')
                      : t('admin.service_settings.smtp_username_placeholder', {}, 'Usually the full email address')
                  }
                />
              </label>
              <label className={labelClassName()}>
                {t('admin.service_settings.smtp_password_label', {}, 'SMTP password')} {secretConfigured.email
                  ? t('admin.service_settings.secret_configured_suffix', {}, '(configured)')
                  : t('admin.service_settings.secret_missing_suffix', {}, '(not configured)')}
                <input className={fieldClassName()} type="password" value={emailForm.smtp_password} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, smtp_password: event.target.value }))} placeholder={secretConfigured.email ? t('admin.service_settings.email_password_keep_placeholder', {}, 'Leave empty to keep the current password') : t('admin.service_settings.email_password_required_placeholder', {}, 'Required when username is set')} />
              </label>
              <label className={labelClassName()}>
                {t('admin.service_settings.from_email_label', {}, 'Sender email')}
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
                {t('admin.service_settings.from_name_label', {}, 'Sender name')}
                <input className={fieldClassName()} value={emailForm.from_name} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, from_name: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                {t('admin.service_settings.reply_to_label', {}, 'Reply-to email')}
                <input className={fieldClassName()} value={emailForm.reply_to} disabled={loading} onChange={(event) => setEmailForm((current) => ({ ...current, reply_to: event.target.value }))} />
              </label>
              <label className={labelClassName()}>
                {t('admin.service_settings.timeout_seconds_label', {}, 'Timeout (seconds)')}
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
                  {t('admin.service_settings.enabled_label', {}, 'Enabled')}
                </label>
              </div>
              <div className="flex justify-end">
                <button type="submit" className="btn btn-primary" disabled={saving === 'email'}>
                  {saving === 'email'
                    ? t('admin.service_settings.saving', {}, 'Saving')
                    : t('common.save', {}, 'Save')}
                </button>
              </div>
            </form>
            </section>

            <section className="grid gap-3 border-t border-slate-200 pt-6 dark:border-slate-800 lg:grid-cols-[1fr_auto]">
            <label className={labelClassName()}>
              {t('admin.service_settings.test_recipient_label', {}, 'Test recipient')}
              <input className={fieldClassName()} value={emailTestRecipient} onChange={(event) => setEmailTestRecipient(event.target.value)} placeholder="operator@example.com" />
            </label>
            <div className="flex items-end justify-end">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving === 'email-test' || !emailTestRecipient}
                onClick={() => postJson('/api/admin/service-settings/email/test', { recipient_email: emailTestRecipient }, 'email-test', t('admin.service_settings.email_test_sent', {}, 'Test email sent.'))}
              >
                {t('admin.service_settings.send_test_email', {}, 'Send test email')}
              </button>
            </div>
            </section>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeTab === 'payment' ? (
        <BackofficeSectionPanel>
          <div id="service-settings-payment" className="space-y-8" role="tabpanel">
            <section className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  Alipay
                </p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                  {t('admin.service_settings.alipay_title', {}, '支付宝支付')}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t('admin.service_settings.alipay_desc', {}, '保存支付宝网页支付所需凭证。密钥加密存储，不会在页面回显。')}
                </p>
              </div>

              <form className="grid gap-4 lg:grid-cols-2" onSubmit={submitAlipay}>
                <label className={labelClassName()}>
                  App ID
                  <input
                    className={fieldClassName()}
                    value={alipayForm.app_id}
                    disabled={loading}
                    onChange={(event) => setAlipayForm((current) => ({ ...current, app_id: event.target.value }))}
                  />
                </label>
                <label className={labelClassName()}>
                  {t('admin.service_settings.alipay_gateway_url_label', {}, '支付宝网关')}
                  <input
                    className={fieldClassName()}
                    value={alipayForm.gateway_url}
                    disabled={loading}
                    onChange={(event) => setAlipayForm((current) => ({ ...current, gateway_url: event.target.value }))}
                    placeholder="https://openapi.alipay.com/gateway.do"
                  />
                </label>

                <div className="lg:col-span-2">
                  <div className={labelClassName()}>
                    {t('admin.service_settings.alipay_notify_url_label', {}, '异步通知地址')}
                    <div className="mt-1 grid gap-2 lg:grid-cols-[1fr_auto]">
                      <input
                        className={fieldClassName()}
                        value={resolvedAlipayNotifyUrl}
                        readOnly
                        disabled={loading}
                        placeholder={t('admin.service_settings.alipay_url_placeholder', {}, '保存门户基础地址后自动生成')}
                      />
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={!resolvedAlipayNotifyUrl}
                        onClick={() => void copyText(resolvedAlipayNotifyUrl, t('admin.service_settings.alipay_notify_copied', {}, '支付宝异步通知地址已复制。'))}
                      >
                        {t('common.copy', {}, 'Copy')}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="lg:col-span-2">
                  <div className={labelClassName()}>
                    {t('admin.service_settings.alipay_return_url_label', {}, '同步返回地址')}
                    <div className="mt-1 grid gap-2 lg:grid-cols-[1fr_auto]">
                      <input
                        className={fieldClassName()}
                        value={resolvedAlipayReturnUrl}
                        readOnly
                        disabled={loading}
                        placeholder={t('admin.service_settings.alipay_url_placeholder', {}, '保存门户基础地址后自动生成')}
                      />
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={!resolvedAlipayReturnUrl}
                        onClick={() => void copyText(resolvedAlipayReturnUrl, t('admin.service_settings.alipay_return_copied', {}, '支付宝同步返回地址已复制。'))}
                      >
                        {t('common.copy', {}, 'Copy')}
                      </button>
                    </div>
                  </div>
                </div>

                <label className={labelClassName()}>
                  {t('admin.service_settings.alipay_private_key_label', {}, '应用私钥')} {secretConfigured.alipayPrivateKey
                    ? t('admin.service_settings.secret_configured_suffix', {}, '(configured)')
                    : t('admin.service_settings.secret_missing_suffix', {}, '(not configured)')}
                  <textarea
                    className={`${fieldClassName()} min-h-32 font-mono`}
                    value={alipayForm.private_key}
                    disabled={loading}
                    onChange={(event) => setAlipayForm((current) => ({ ...current, private_key: event.target.value }))}
                    placeholder={secretConfigured.alipayPrivateKey ? t('admin.service_settings.secret_keep_placeholder', {}, '留空则保留当前密钥') : t('admin.service_settings.alipay_private_key_placeholder', {}, '粘贴 PEM 格式应用私钥')}
                  />
                </label>
                <label className={labelClassName()}>
                  {t('admin.service_settings.alipay_public_key_label', {}, '支付宝公钥')} {secretConfigured.alipayPublicKey
                    ? t('admin.service_settings.secret_configured_suffix', {}, '(configured)')
                    : t('admin.service_settings.secret_missing_suffix', {}, '(not configured)')}
                  <textarea
                    className={`${fieldClassName()} min-h-32 font-mono`}
                    value={alipayForm.public_key}
                    disabled={loading}
                    onChange={(event) => setAlipayForm((current) => ({ ...current, public_key: event.target.value }))}
                    placeholder={secretConfigured.alipayPublicKey ? t('admin.service_settings.secret_keep_placeholder', {}, '留空则保留当前密钥') : t('admin.service_settings.alipay_public_key_placeholder', {}, '粘贴 PEM 格式支付宝公钥')}
                  />
                </label>

                <div className="flex flex-col gap-3 border-t border-slate-200 pt-4 dark:border-slate-800 lg:col-span-2 lg:flex-row lg:items-center lg:justify-between">
                  <div className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                    <button
                      type="button"
                      role="switch"
                      aria-label={t('admin.service_settings.alipay_toggle_label', {}, '启用支付宝支付')}
                      aria-checked={alipayForm.enabled}
                      className={switchButtonClassName(alipayForm.enabled)}
                      disabled={loading}
                      onClick={() => setAlipayForm((current) => ({ ...current, enabled: !current.enabled }))}
                    >
                      <span className={switchKnobClassName(alipayForm.enabled)} />
                    </button>
                    {t('admin.service_settings.alipay_enabled_label', {}, '启用支付宝支付')}
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={saving === 'alipay-test'}
                      onClick={() => postJson('/api/admin/service-settings/alipay-payment/test', {}, 'alipay-test', t('admin.service_settings.alipay_test_done', {}, '支付宝配置检查完成。'))}
                    >
                      {saving === 'alipay-test'
                        ? t('admin.service_settings.checking', {}, 'Checking')
                        : t('admin.service_settings.check_alipay', {}, '检查支付宝配置')}
                    </button>
                    <button type="submit" className="btn btn-primary" disabled={saving === 'alipay-payment'}>
                      {saving === 'alipay-payment'
                        ? t('admin.service_settings.saving', {}, 'Saving')
                        : t('admin.service_settings.save_alipay', {}, '保存支付宝配置')}
                    </button>
                  </div>
                </div>
              </form>
            </section>
          </div>
        </BackofficeSectionPanel>
      ) : null}
    </BackofficePageStack>
  );
}
