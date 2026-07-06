import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const pagePath = fromFrontendRoot('src/app/admin/service-settings/page.tsx');
const source = readFileSync(pagePath, 'utf8');

assert.match(
  source,
  /type ServiceSettingsTab = 'login' \| 'email' \| 'payment';/,
  'service settings page must split content into login, email, and payment tabs'
);

assert.match(
  source,
  /label: t\('admin\.service_settings\.tab_login', \{\}, '登录配置'\)[\s\S]*label: t\('admin\.service_settings\.tab_email', \{\}, '邮件配置'\)[\s\S]*label: t\('admin\.service_settings\.tab_payment', \{\}, '支付配置'\)/,
  'service settings tabs must use Chinese operator label fallbacks'
);

assert.match(
  source,
  /async function readBackendPayload\(response: Response\)/,
  'service settings page must parse backend responses through a safe helper'
);

assert.match(
  source,
  /contentType\.includes\('application\/json'\)/,
  'safe response helper must inspect content-type before JSON parsing'
);

assert.doesNotMatch(
  source,
  /const payload = await response\.json\(\);/,
  'service settings requests must not blindly parse non-JSON 500 responses as JSON'
);

assert.match(
  source,
  /请确认数据库迁移已执行/,
  'service settings page must explain likely migration failure in Chinese'
);

assert.match(
  source,
  /service_settings\.email_tls_mode_invalid/,
  'service settings page must translate the SMTP TLS mode validation error'
);

assert.match(
  source,
  /service_settings\.email_delivery_failed/,
  'service settings page must translate SMTP delivery failures'
);

assert.match(
  source,
  /SMTP 服务器拒绝认证/,
  'service settings page must explain SMTP authentication failures in Chinese'
);

assert.match(
  source,
  /smtp_username_same_as_from_email: boolean;/,
  'service settings email form must track whether SMTP username follows from_email'
);

assert.match(
  source,
  /const \[emailConfigExpanded, setEmailConfigExpanded\] = useState\(false\);/,
  'low-frequency SMTP fields must be hidden behind an explicit expanded state'
);

assert.match(
  source,
  /setEmailConfigExpanded\(email\.status === 'missing_config' \|\| email\.status === 'error'\);/,
  'SMTP config should auto-expand only when missing or errored'
);

assert.match(
  source,
  /const \[emailPreviewOpen, setEmailPreviewOpen\] = useState\(false\);/,
  'email template preview must live behind an explicit drawer state'
);

assert.match(
  source,
  /role="dialog"[\s\S]*aria-modal="true"[\s\S]*email-preview-drawer-title/,
  'email template preview must render as a modal drawer instead of always occupying the settings page'
);

assert.match(
  source,
  /onClick=\{openEmailPreviewDrawer\}/,
  'email settings page must expose a dedicated action to open the preview drawer'
);

assert.match(
  source,
  /同发件邮箱/,
  'service settings page must expose a same-as-from-email SMTP username shortcut'
);

assert.match(
  source,
  /smtp_username: emailForm\.smtp_username_same_as_from_email\s*\?\s*emailForm\.from_email\s*:\s*emailForm\.smtp_username/,
  'service settings save payload must use from_email as SMTP username when the shortcut is enabled'
);

assert.match(
  source,
  /disabled=\{loading \|\| emailForm\.smtp_username_same_as_from_email\}/,
  'SMTP username input must be disabled while following from_email'
);

assert.match(
  source,
  /errorCode\.startsWith\('service_settings\.'\)/,
  'structured service settings errors must not show the database migration hint'
);

assert.match(
  source,
  /SMTP 加密方式不能同时启用 SSL 和 STARTTLS/,
  'service settings page must explain mutually exclusive SMTP TLS modes in Chinese'
);

assert.match(
  source,
  /function buildAlipayNotifyUrl\(publicBaseUrl: string\)[\s\S]*\/open\/payments\/alipay\/notify/,
  'Alipay notify URL must be generated from the public base URL'
);

assert.match(
  source,
  /function buildAlipayReturnUrl\(publicBaseUrl: string\)[\s\S]*\/open\/payments\/alipay\/return/,
  'Alipay return URL must be generated from the public base URL'
);

assert.match(
  source,
  /\/api\/admin\/service-settings\/alipay-payment/,
  'service settings page must save Alipay payment settings through the admin service-settings API'
);

assert.match(
  source,
  /\/api\/admin\/service-settings\/alipay-payment\/test/,
  'service settings page must expose an Alipay configuration check action'
);

assert.match(
  source,
  /alipayPrivateKey:[\s\S]*secrets\.private_key\?\.configured[\s\S]*alipayPublicKey:[\s\S]*secrets\.public_key\?\.configured/,
  'Alipay key state must be displayed as configured or missing instead of echoing key values'
);

assert.doesNotMatch(
  source,
  /value=\{stringValue\(alipay\.secrets|value=\{data\?\.settings\.alipay_payment\.secrets/,
  'Alipay secret values must never be echoed into the form'
);

assert.match(
  source,
  /function buildQqRedirectUri\(publicBaseUrl: string\)/,
  'QQ redirect URI must be generated from the public base URL instead of hand-entered'
);

assert.match(
  source,
  /return `\$\{parsed\.protocol\}\/\/\$\{parsed\.host\}\/open\/auth\/qq\/callback`;/,
  'QQ redirect URI generation must use the normalized /open/auth/qq/callback path'
);

assert.match(
  source,
  /const qqRedirectUri = useMemo/,
  'service settings page must derive the QQ redirect URI as a computed value'
);

assert.match(
  source,
  /redirect_uri: qqRedirectUri,[\s\S]*scope: 'get_user_info',[\s\S]*timeout_seconds: 10,/,
  'QQ save payload must use generated callback, fixed scope, and default timeout'
);

assert.doesNotMatch(
  source,
  /value=\{qqForm\.scope\}/,
  'QQ OAuth scope must not be exposed as a routine editable field'
);

assert.doesNotMatch(
  source,
  /value=\{qqForm\.timeout_seconds\}/,
  'QQ OAuth timeout must not be exposed as a routine editable field'
);

assert.match(
  source,
  /role="switch"[\s\S]*aria-label=\{t\('admin\.service_settings\.qq_toggle_label', \{\}, '启用 QQ 快捷登录'\)\}/,
  'QQ enable control must render as a switch'
);

assert.match(
  source,
  /QQ 回调地址已复制/,
  'service settings page must provide a copy action for the generated QQ callback URL'
);

assert.match(
  source,
  /门户基础地址[\s\S]*保存基础地址[\s\S]*QQ 快捷登录[\s\S]*保存 QQ 配置/,
  'portal base URL and QQ login sections must use distinct save labels'
);

assert.match(
  source,
  /回调地址由门户基础地址自动生成/,
  'QQ login section must explain that callback URLs are derived from the portal base URL'
);

assert.match(
  source,
  /smtp_use_ssl: event\.target\.checked, smtp_use_starttls: event\.target\.checked \? false : current\.smtp_use_starttls/,
  'enabling SSL must turn off STARTTLS in the service settings form'
);

assert.match(
  source,
  /smtp_use_starttls: event\.target\.checked, smtp_use_ssl: event\.target\.checked \? false : current\.smtp_use_ssl/,
  'enabling STARTTLS must turn off SSL in the service settings form'
);

console.log('admin_service_settings_ui_contract: ok');
