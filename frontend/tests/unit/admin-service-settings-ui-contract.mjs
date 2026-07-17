import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const pagePath = fromFrontendRoot('src/app/admin/service-settings/page.tsx');
const source = readFileSync(pagePath, 'utf8');

assert.match(
  source,
  /type ServiceSettingsTab = 'portal' \| 'qq' \| 'email' \| 'payment';/,
  'service settings page must expose one independent configuration group per tab'
);

assert.match(
  source,
  /label: t\('admin\.service_settings\.tab_portal', \{\}, '门户地址'\)[\s\S]*label: t\('admin\.service_settings\.tab_qq', \{\}, 'QQ 登录'\)[\s\S]*label: t\('admin\.service_settings\.tab_email', \{\}, '邮件配置'\)[\s\S]*label: t\('admin\.service_settings\.tab_payment', \{\}, '支付配置'\)/,
  'service settings group navigation must use task-specific Chinese operator labels'
);

assert.match(
  source,
  /activeTab === 'portal'[\s\S]*id="service-settings-portal"[\s\S]*activeTab === 'qq'[\s\S]*id="service-settings-qq"/,
  'Portal URL and QQ login must not render as two simultaneous forms in one group'
);

assert.match(
  source,
  /savedForms, setSavedForms] = useState<SavedServiceSettingsForms[\s\S]*activeGroupDirty = \(\(\) =>[\s\S]*restoreActiveGroup/,
  'configuration groups must compare against saved state and support explicit discard'
);

assert.match(
  source,
  /pendingTab[\s\S]*requestTabChange[\s\S]*<ConfirmModal[\s\S]*discard_and_switch/,
  'switching groups with unsaved changes must require confirmation'
);

assert.match(
  source,
  /pendingNavigationHref[\s\S]*setPendingNavigationHref[\s\S]*addEventListener\('beforeunload'[\s\S]*unsaved_leave_title[\s\S]*discard_and_leave/,
  'unsaved configuration must use an application confirmation for internal navigation and browser protection for unload'
);
assert.doesNotMatch(source, /window\.confirm/, 'service settings must not use a browser-native confirmation dialog');

assert.match(
  source,
  /activeValidationIssues = \(\(\) =>[\s\S]*validation_public_url[\s\S]*validation_qq_app_id[\s\S]*validation_email_host[\s\S]*validation_payment_app_id/,
  'each configuration group must expose contextual client validation'
);

assert.match(
  source,
  /useToast\(\)[\s\S]*operation_completed_title/,
  'transient configuration success must use the global Toast surface'
);

assert.doesNotMatch(
  source,
  /\{notice \? \([\s\S]*role="status"/,
  'success feedback must not insert a notice card into the configuration workspace'
);

assert.match(
  source,
  /settingsRequestActiveRef = useRef[\s\S]*settingsRequestSequenceRef = useRef/,
  'initial service settings loading must deduplicate React development requests'
);

assert.match(
  source,
  /createApiClient[\s\S]*serviceSettingsClient\.request<ServiceSettingsData>/,
  'service settings page must parse backend responses through the shared strict client'
);

assert.match(
  source,
  /function serviceSettingsRequestErrorMessage[\s\S]*error instanceof ApiError/,
  'service settings page must preserve structured backend error handling'
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
  /已有 SMTP 密码密文无法用当前运行时密钥读取/,
  'service settings page must explain unreadable saved SMTP password ciphertext without blaming database migration'
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
  /function inferBrowserPublicBaseUrl\(\): string[\s\S]*window\.location\.origin[\s\S]*parsed\.protocol !== 'http:' && parsed\.protocol !== 'https:'[\s\S]*parsed\.hostname === 'localhost'[\s\S]*parsed\.hostname\.startsWith\('127\.'\)[\s\S]*return `\$\{parsed\.protocol\}\/\/\$\{parsed\.host\}`;/,
  'Alipay setup should be able to infer the current public base URL from the admin page origin'
);

assert.match(
  source,
  /const \[browserPublicBaseUrl, setBrowserPublicBaseUrl\] = useState\(''\);[\s\S]*setBrowserPublicBaseUrl\(inferBrowserPublicBaseUrl\(\)\);/,
  'service settings page must store the inferred current public base URL'
);

assert.match(
  source,
  /const effectivePortalPublicBaseUrl = savedPortalPublicBaseUrl \|\| browserPublicBaseUrl;[\s\S]*const portalPublicAutosavePending = !savedPortalPublicBaseUrl && Boolean\(browserPublicBaseUrl\);/,
  'Alipay callback URLs must fall back to the current admin origin when no portal base URL has been saved yet'
);

assert.match(
  source,
  /\/api\/admin\/service-settings\/portal-public[\s\S]*enabled: true,[\s\S]*public_base_url: browserPublicBaseUrl,[\s\S]*\/api\/admin\/service-settings\/alipay-payment/,
  'saving enabled Alipay settings must autosave the portal base URL before saving Alipay settings when it is missing'
);

assert.match(
  source,
  /alipay_callback_base_label[\s\S]*alipay_public_url_autosave_notice/,
  'Alipay settings must show the callback base URL and explain autosave behavior'
);

assert.match(
  source,
  /alipay_callback_console_guidance[\s\S]*md:grid-cols-2[\s\S]*alipay_notify_url_label[\s\S]*alipay_return_url_label/,
  'Alipay callback URLs must be shown side by side with clear console guidance'
);

assert.match(
  source,
  /alipay_notify_url_hint[\s\S]*唯一的支付确认依据[\s\S]*alipay_return_url_hint[\s\S]*不代表支付成功/,
  'Alipay settings must distinguish the authoritative notify callback from the browser return callback'
);

assert.doesNotMatch(
  source,
  /value=\{alipayForm\.gateway_url\}/,
  'the fixed Alipay gateway must not be exposed as an editable operator setting'
);

assert.match(
  source,
  /Could not deserialize key data\|ASN\\\.1[\s\S]*error_alipay_key_format/,
  'Alipay key parser failures must be translated into an operator-friendly key-format message'
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
