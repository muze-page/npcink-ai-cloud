import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/service-settings/page.tsx');
const source = readFileSync(pagePath, 'utf8');

assert.match(
  source,
  /type ServiceSettingsTab = 'login' \| 'email';/,
  'service settings page must split content into login and email tabs'
);

assert.match(
  source,
  /label: '登录配置'[\s\S]*label: '邮件配置'/,
  'service settings tabs must use Chinese operator labels'
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
  /smtp_use_ssl: event\.target\.checked, smtp_use_starttls: event\.target\.checked \? false : current\.smtp_use_starttls/,
  'enabling SSL must turn off STARTTLS in the service settings form'
);

assert.match(
  source,
  /smtp_use_starttls: event\.target\.checked, smtp_use_ssl: event\.target\.checked \? false : current\.smtp_use_ssl/,
  'enabling STARTTLS must turn off SSL in the service settings form'
);

console.log('admin_service_settings_ui_contract: ok');
