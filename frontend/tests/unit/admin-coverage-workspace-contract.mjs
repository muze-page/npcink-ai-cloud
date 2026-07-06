import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const coverageSource = readFileSync(resolve(process.cwd(), 'src/app/admin/coverage/page.tsx'), 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(
  coverageSource,
  /title=\{t\('admin\.coverage_surface_title'[\s\S]*Customer service workspace/,
  'Coverage surface must be framed as a customer service workspace'
);

assert.match(
  coverageSource,
  /const selectedQueueItem = visibleItems\[0\] \|\| visibleQueueItems\[0\] \|\| null/,
  'Coverage workspace must derive a current customer focus for the inspector'
);

assert.match(
  coverageSource,
  /admin\.coverage\.inspector_title[\s\S]*selectedQueueItem[\s\S]*admin\.coverage\.inspector_boundary/,
  'Coverage workspace must show a right-side customer inspector with a boundary note'
);

assert.match(
  coverageSource,
  /admin\.coverage\.inspector_boundary[\s\S]*checkout, payment, or WordPress write controls/,
  'Coverage inspector must not become customer-facing checkout, payment, or WordPress write control'
);

assert.match(
  i18nSource,
  /'admin\.coverage_surface_title': '客户服务工作区'/,
  'Coverage workspace must provide Simplified Chinese title copy'
);

assert.match(
  i18nSource,
  /'admin\.coverage\.inspector_title': '当前客户焦点'[\s\S]*'admin\.coverage\.inspector_boundary': '这个检查器只打开现有客户、订阅、站点和套餐界面，不创建客户侧 checkout、支付或 WordPress 写入控制。'/,
  'Coverage inspector must provide Simplified Chinese boundary copy'
);

assert.doesNotMatch(
  coverageSource,
  /invoice_create|createCheckout|paymentIntent|wordpress_write|auto_apply|publish_to_wordpress/i,
  'Coverage workspace must not introduce commercial front-office or WordPress write actions'
);

console.log('admin_coverage_workspace_contract: ok');
