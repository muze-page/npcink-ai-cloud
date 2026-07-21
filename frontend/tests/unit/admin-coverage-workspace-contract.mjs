import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const coverageSource = readFileSync(resolve(process.cwd(), 'src/app/admin/coverage/page.tsx'), 'utf8');
const layoutSource = readFileSync(resolve(process.cwd(), 'src/app/admin/layout.tsx'), 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');

assert.match(
  coverageSource,
  /title=\{t\('admin\.coverage_surface_title'[\s\S]*Service risk queue/,
  'Coverage surface must be framed as the canonical service risk queue'
);

assert.match(
  coverageSource,
  /useSearchParams\(\)[\s\S]*updateQueueUrl[\s\S]*status[\s\S]*reason[\s\S]*sort[\s\S]*focus/,
  'Coverage filters, sort, and inspector focus must survive refresh and detail navigation through the URL'
);

assert.match(
  coverageSource,
  /type QueueSort = 'priority' \| 'expiry' \| 'customer'[\s\S]*searchQuery[\s\S]*reasonFilter[\s\S]*visibleItems = useMemo/,
  'Coverage queue must support search, reason filtering, and explicit prioritization'
);

assert.match(
  coverageSource,
  /visibleItems\.find\(\(item\) => queueItemKey\(item\) === selectedKey\)[\s\S]*admin\.coverage\.select_inspector_action/,
  'Coverage inspector must follow an explicit operator selection instead of always taking the first row'
);

assert.match(
  coverageSource,
  /admin\.coverage\.inspector_title[\s\S]*selectedQueueItem[\s\S]*admin\.coverage\.inspector_boundary/,
  'Coverage workspace must show a right-side customer inspector with a boundary note'
);

assert.doesNotMatch(
  coverageSource,
  /tab_packages|activeTab|setActiveTab|\/api\/admin\/plans/,
  'Coverage workspace must not reintroduce the duplicate package overview tab or fetch the package catalog directly'
);

assert.match(
  coverageSource,
  /href="\/admin\/subscriptions"[\s\S]*admin\.coverage_open_subscription_queue_action/,
  'Coverage workspace must expose subscription risk as a secondary entry'
);

assert.match(
  coverageSource,
  /coverageRequestActiveRef = useRef[\s\S]*coverageRequestSequenceRef = useRef[\s\S]*loadCoverage\(true\)/,
  'Coverage queue must deduplicate initial loading and expose a bounded refresh action'
);

assert.doesNotMatch(
  coverageSource,
  /AdminHorizontalScroll|<table|min-w-\[64rem\]/,
  'The core service queue must not depend on a horizontally scrolling desktop table on mobile'
);

assert.match(
  coverageSource,
  /role="list"[\s\S]*data-ui="coverage-queue-item"[\s\S]*aria-controls="coverage-inspector"/,
  'Coverage queue must use a responsive task list with an explicitly connected inspector'
);

assert.doesNotMatch(
  layoutSource,
  /href: '\/admin\/subscriptions'[\s\S]*labelKey: 'admin\.nav_subscriptions'/,
  'Subscription risk must not return as a top-level admin sidebar entry'
);

assert.match(
  coverageSource,
  /admin\.coverage\.inspector_boundary[\s\S]*checkout, payment, or WordPress write controls/,
  'Coverage inspector must not become customer-facing checkout, payment, or WordPress write control'
);

assert.match(
  i18nSource,
  /'admin\.coverage_surface_title': '服务风险队列'/,
  'Coverage queue must provide task-specific Simplified Chinese title copy'
);

assert.match(
  i18nSource,
  /'admin\.coverage\.refresh_action': '刷新队列'[\s\S]*'admin\.coverage\.search_placeholder': '客户、账户、订阅或套餐'[\s\S]*'admin\.coverage\.sort_priority': '影响最高'[\s\S]*'admin\.coverage\.inspector_boundary': '这个检查器只打开现有客户、订阅、站点和套餐界面，不创建客户侧 checkout、支付或 WordPress 写入控制。'/,
  'Coverage toolbar and inspector must provide Simplified Chinese utility copy'
);

assert.doesNotMatch(
  coverageSource,
  /invoice_create|createCheckout|paymentIntent|wordpress_write|auto_apply|publish_to_wordpress/i,
  'Coverage workspace must not introduce commercial front-office or WordPress write actions'
);

console.log('admin_coverage_workspace_contract: ok');
