import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const portalNavbarPath = resolve(root, 'src/components/portal/PortalNavbar.tsx');
const portalSupportPagePath = resolve(root, 'src/app/portal/support/page.tsx');
const portalSupportDetailPagePath = resolve(root, 'src/app/portal/support/[requestId]/page.tsx');
const portalBillingPagePath = resolve(root, 'src/app/portal/billing/page.tsx');
const portalClientPath = resolve(root, 'src/lib/portal-client.ts');
const adminLayoutPath = resolve(root, 'src/app/admin/layout.tsx');
const adminSupportPagePath = resolve(root, 'src/app/admin/support-requests/page.tsx');
const adminSupportDetailPagePath = resolve(root, 'src/app/admin/support-requests/[requestId]/page.tsx');
const adminProxyPath = resolve(root, 'src/app/api/admin/[...path]/route.ts');
const i18nPath = resolve(root, 'src/lib/i18n.ts');

const portalNavbarSource = readFileSync(portalNavbarPath, 'utf8');
const portalSupportPageSource = readFileSync(portalSupportPagePath, 'utf8');
const portalSupportDetailPageSource = readFileSync(portalSupportDetailPagePath, 'utf8');
const portalBillingPageSource = readFileSync(portalBillingPagePath, 'utf8');
const portalClientSource = readFileSync(portalClientPath, 'utf8');
const adminLayoutSource = readFileSync(adminLayoutPath, 'utf8');
const adminSupportPageSource = readFileSync(adminSupportPagePath, 'utf8');
const adminSupportDetailPageSource = readFileSync(adminSupportDetailPagePath, 'utf8');
const adminProxySource = readFileSync(adminProxyPath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');

assert.match(
  portalNavbarSource,
  /href: '\/portal\/support'[\s\S]*portal\.nav_support_requests/,
  'Portal navigation must expose a support request tab'
);
assert.match(
  portalSupportPageSource,
  /portalClient\.listSupportRequests[\s\S]*portalClient\.createSupportRequest/,
  'Portal support page must list and create support requests through the Portal client'
);
assert.match(
  portalSupportPageSource,
  /<ListPagination[\s\S]*offset=\{offset\}[\s\S]*total=\{total\}/,
  'Portal support history must expose all tickets through pagination'
);
assert.match(
  portalSupportPageSource,
  /SUPPORT_TOPICS[\s\S]*billing[\s\S]*payment[\s\S]*site[\s\S]*usage[\s\S]*account[\s\S]*general/,
  'Portal support form must expose bounded customer-support topics'
);
assert.match(
  portalSupportPageSource,
  /support_rule_open[\s\S]*support_rule_in_progress[\s\S]*support_rule_resolved[\s\S]*support_rule_closed[\s\S]*data-portal-support="status-rules"/,
  'Portal support page must explain ticket status, close evaluation, and reopen expectations'
);
assert.match(
  portalBillingPageSource,
  /\/portal\/support\?new=1&topic=billing/,
  'Portal package page must open the ticket form for package or payment issues'
);
assert.doesNotMatch(
  portalBillingPageSource,
  /\/portal\/support\?new=1&topic=billing&site=|encodeURIComponent\(selectedSiteId\)/,
  'Portal package page must open account-level billing tickets without preselecting a site'
);
assert.doesNotMatch(
  portalSupportPageSource,
  /const initialSiteId = searchParams\?\.get\('site'\) \|\| selectedSiteId|if \(!siteId && selectedSiteId\)/,
  'Portal support form must default to account-level issues unless a site is explicitly passed'
);
assert.doesNotMatch(
  portalBillingPageSource,
  /portal\.billing\.help_title|portal\.billing\.help_desc/,
  'Portal package page must not keep a separate help card after the ticket tab exists'
);
assert.match(
  portalClientSource,
  /async getAccountEntitlements[\s\S]*\/account\/entitlements[\s\S]*async createAccountCreditPackOrder[\s\S]*\/account\/credit-pack-orders/,
  'Portal client must expose account-level package, credit pack, and payment operations'
);
assert.match(
  portalClientSource,
  /async listSupportRequests[\s\S]*\/support-requests/,
  'Portal client must expose support request listing'
);
assert.match(
  portalClientSource,
  /async createSupportRequest[\s\S]*'POST', '\/support-requests'/,
  'Portal client must expose support request creation'
);
assert.match(
  portalClientSource,
  /async getSupportRequest[\s\S]*\/support-requests\/\$\{requestId\}/,
  'Portal client must expose support request detail loading'
);
assert.match(
  portalClientSource,
  /async createSupportRequestMessage[\s\S]*'POST', `\/support-requests\/\$\{requestId\}\/messages`/,
  'Portal client must expose customer ticket replies'
);
assert.match(
  portalSupportDetailPageSource,
  /portalClient\.getSupportRequest[\s\S]*portalClient\.createSupportRequestMessage/,
  'Portal ticket detail page must load messages and let customers reply'
);
assert.match(
  portalSupportDetailPageSource,
  /createSupportRequestAttachment[\s\S]*getSupportRequestAttachment[\s\S]*submitSupportRequestFeedback/,
  'Portal ticket detail page must support attachments, downloads, and close evaluation'
);
assert.match(
  adminLayoutSource,
  /href: '\/admin\/support-requests'[\s\S]*admin\.nav_support_requests/,
  'Admin navigation must expose the support request queue'
);
assert.match(
  adminSupportPageSource,
  /fetch\(`\/api\/admin\/support-requests\?\$\{params\.toString\(\)\}`/,
  'Admin support page must load the support request queue through the admin proxy'
);
assert.match(
  adminSupportPageSource,
  /params\.set\('offset'[\s\S]*<ListPagination[\s\S]*total=\{total\}/,
  'Admin support queue must expose all filtered tickets through pagination'
);
assert.match(
  adminSupportPageSource,
  /\/api\/admin\/support-requests\/\$\{encodeURIComponent\(requestId\)\}[\s\S]*method: 'PATCH'/,
  'Admin support page must update ticket status through the admin proxy'
);
assert.match(
  adminSupportPageSource,
  /params\.set\('topic', topic\)[\s\S]*topicFilter/,
  'Admin support queue must expose the backend topic filter'
);
assert.match(
  adminSupportPageSource,
  /href=\{`\/admin\/support-requests\/\$\{encodeURIComponent\(item\.request_id\)\}`\}/,
  'Admin support queue must link to ticket detail'
);
assert.match(
  adminSupportDetailPageSource,
  /createSupportRequestMessage[\s\S]*visibility[\s\S]*public[\s\S]*internal/,
  'Admin ticket detail must support public replies and internal notes'
);
assert.match(
  adminSupportDetailPageSource,
  /createSupportRequestAttachment[\s\S]*fetchSupportRequestAttachment[\s\S]*support_feedback_title/,
  'Admin ticket detail must support attachments and show close evaluation'
);
assert.match(
  adminProxySource,
  /PATCH[\s\S]*\^support-requests\\\/\[\^\/\]\+\$/,
  'Admin proxy must route support request status updates to the admin service namespace'
);
assert.match(
  adminProxySource,
  /POST[\s\S]*\^support-requests\\\/\[\^\/\]\+\\\/messages\$/,
  'Admin proxy must route support request message creation to the admin service namespace'
);
assert.match(
  i18nSource,
  /portal\.nav_support_requests[\s\S]*portal\.support_status_in_progress[\s\S]*admin\.nav_support_requests[\s\S]*admin\.support_status_in_progress/,
  'Support request Portal and Admin labels must be localized'
);
assert.match(
  i18nSource,
  /portal\.support_status_rules_title[\s\S]*portal\.support_rule_closed[\s\S]*portal\.support_status_rules_title[\s\S]*portal\.support_rule_closed/,
  'Support status rule copy must be localized in English and Chinese'
);
