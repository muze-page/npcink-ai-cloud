import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const navbarPath = resolve(process.cwd(), 'src/components/portal/PortalNavbar.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');
const aiInsightsPagePath = resolve(process.cwd(), 'src/app/portal/ai-insights/page.tsx');
const monitoringPath = resolve(process.cwd(), 'src/app/portal/monitoring/page.tsx');
const auditPath = resolve(process.cwd(), 'src/app/portal/audit/PortalAuditClient.tsx');
const navbarSource = readFileSync(navbarPath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');
const monitoringSource = readFileSync(monitoringPath, 'utf8');
const auditSource = readFileSync(auditPath, 'utf8');

const primaryStart = navbarSource.indexOf('const primaryNavItems');
const primaryEnd = navbarSource.indexOf('const isActive', primaryStart);
const primarySource = navbarSource.slice(primaryStart, primaryEnd);

assert.ok(primaryStart >= 0 && primaryEnd > primaryStart, 'portal navbar must declare primary navigation');

const primaryHrefs = Array.from(primarySource.matchAll(/href:\s*'([^']+)'/g), (match) => match[1]);
assert.deepEqual(
  primaryHrefs,
  ['/portal', '/portal/billing', '/portal/usage', '/portal/support', '/portal/account'],
  'portal primary nav must merge overview and sites into service while keeping package, usage, tickets, and account'
);
assert.doesNotMatch(primarySource, /\/portal\/sites/, 'sites must not remain a separate primary navigation entry');

assert.doesNotMatch(
  primarySource,
  /\/portal\/monitoring|\/portal\/ai-insights|\/portal\/audit/,
  'monitoring, AI insight, and audit routes must not return to primary user navigation'
);

assert.doesNotMatch(
  navbarSource,
  /secondaryNavItems|portal\.nav_more|portal\.site_admin_workspace|\/portal\/monitoring|\/portal\/ai-insights|\/portal\/audit/,
  'advanced support, monitoring, AI insight, audit routes, and duplicate header badges must not return to customer navigation'
);
assert.equal(
  existsSync(aiInsightsPagePath),
  false,
  'AI insights must not remain as a standalone customer Portal page'
);
assert.match(
  monitoringSource,
  /router\.replace\(`\/portal\/sites\/\$\{encodeURIComponent\(selectedSite\.site_id\)\}#service-status`\)/,
  'legacy monitoring links must resolve to the canonical site service-status section'
);
assert.match(
  auditSource,
  /data-portal-support-deeplink="audit"/,
  'recent activity may remain only as a support-request deep link'
);
assert.match(
  navbarSource,
  /\{isAuthenticated \? \([\s\S]*<nav data-ui="portal-primary-nav"/,
  'portal desktop business navigation must only render after the user is authenticated'
);
assert.match(
  navbarSource,
  /\{isAuthenticated \? \([\s\S]*primaryNavItems\.map\(\(item\) => \([\s\S]*onClick=\{\(\) => setMobileNavOpen\(false\)\}/,
  'portal mobile business navigation must only render after the user is authenticated'
);
assert.match(
  navbarSource,
  /const isLoginPage = pathname === '\/portal\/login'/,
  'portal navbar must know when it is already on the login page'
);
assert.match(
  navbarSource,
  /: !isLoginPage \? \([\s\S]*href="\/portal\/login"/,
  'portal navbar must not show a redundant sign-in link on the login page'
);

assert.match(i18nSource, /'portal\.nav_package': 'Package'/, 'English nav copy must expose package as its own entry');
assert.match(i18nSource, /'portal\.nav_service': 'Service'/, 'English nav copy must expose the merged service entry');
assert.match(i18nSource, /'portal\.nav_usage': 'Usage'/, 'English nav copy must expose usage as its own entry');
assert.match(i18nSource, /'portal\.workspace_label': 'Overview'/, 'English overview copy must name the user summary surface');
assert.match(i18nSource, /'portal\.nav_support_requests': 'Tickets'/, 'English nav copy must expose support tickets as their own entry');
assert.match(i18nSource, /'portal\.nav_account': 'Account'/, 'English nav copy must expose account and sign-in settings');
assert.match(i18nSource, /'portal\.nav_package': '套餐'/, 'Chinese nav copy must expose package as its own entry');
assert.match(i18nSource, /'portal\.nav_service': '服务'/, 'Chinese nav copy must expose the merged service entry');
assert.match(i18nSource, /'portal\.nav_usage': '用量'/, 'Chinese nav copy must expose usage as its own entry');
assert.match(i18nSource, /'portal\.workspace_label': '概览'/, 'Chinese overview copy must name the user summary surface');
assert.match(i18nSource, /'portal\.nav_support_requests': '工单'/, 'Chinese nav copy must expose support tickets as their own entry');
assert.match(i18nSource, /'portal\.nav_account': '账号'/, 'Chinese nav copy must expose account and sign-in settings');

console.log('portal_navigation_simplification_contract: ok');
