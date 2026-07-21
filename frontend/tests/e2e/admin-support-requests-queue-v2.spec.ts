import { expect, test, type Page, type Route } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  buildAdminApiErrorEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

type TicketFixture = {
  request_id: string;
  account_id: string;
  site_id: string;
  email: string;
  topic: string;
  title: string;
  description: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  priority: string;
  admin_note: string;
  created_at: string;
  updated_at: string;
};

function initialTickets(): TicketFixture[] {
  return [
    {
      request_id: 'sr_overdue_payment',
      account_id: 'acct_beta',
      site_id: 'site_beta',
      email: 'beta@example.com',
      topic: 'payment',
      title: 'Payment confirmation is still missing',
      description: 'The payment provider returned successfully but the order still shows pending.',
      status: 'open',
      priority: 'normal',
      admin_note: '',
      created_at: '2026-07-08T08:00:00Z',
      updated_at: '2026-07-08T08:00:00Z',
    },
    {
      request_id: 'sr_open_site',
      account_id: 'acct_alpha',
      site_id: 'site_alpha',
      email: 'alpha@example.com',
      topic: 'site',
      title: 'Site connection needs review',
      description: 'The connected site is active but its latest status has not refreshed.',
      status: 'open',
      priority: 'normal',
      admin_note: '',
      created_at: '2026-07-12T05:00:00Z',
      updated_at: '2026-07-12T05:00:00Z',
    },
    {
      request_id: 'sr_progress_usage',
      account_id: 'acct_gamma',
      site_id: 'site_gamma',
      email: 'gamma@example.com',
      topic: 'usage',
      title: 'Usage total needs explanation',
      description: 'The customer needs clarification about the current billing-period usage total.',
      status: 'in_progress',
      priority: 'normal',
      admin_note: 'Checking the current billing snapshot.',
      created_at: '2026-07-10T05:00:00Z',
      updated_at: '2026-07-12T06:00:00Z',
    },
    {
      request_id: 'sr_resolved_account',
      account_id: 'acct_delta',
      site_id: '',
      email: 'delta@example.com',
      topic: 'account',
      title: 'Account display name was corrected',
      description: 'The requested account display-name correction has already been completed.',
      status: 'resolved',
      priority: 'normal',
      admin_note: 'Resolved after identity verification.',
      created_at: '2026-07-09T05:00:00Z',
      updated_at: '2026-07-11T05:00:00Z',
    },
  ];
}

async function installSupportQueueMocks(page: Page) {
  await installAdminMocks(page);
  let tickets = initialTickets();
  let requestCount = 0;
  let failQuery = '';

  await page.route('**/api/admin/support-requests?*', async (route) => {
    requestCount += 1;
    const url = new URL(route.request().url());
    const query = (url.searchParams.get('q') || '').toLowerCase();
    if (failQuery && query === failQuery.toLowerCase()) {
      failQuery = '';
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify(buildAdminApiErrorEnvelope('temporary ticket queue failure')),
      });
      return;
    }
    const status = url.searchParams.get('status') || '';
    const topic = url.searchParams.get('topic') || '';
    const items = tickets.filter((ticket) => {
      const searchable = [ticket.request_id, ticket.email, ticket.title, ticket.account_id, ticket.site_id].join(' ').toLowerCase();
      return (!status || ticket.status === status) && (!topic || ticket.topic === topic) && (!query || searchable.includes(query));
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope({
        items,
        pagination: { total: items.length, limit: 20, offset: 0, has_more: false },
        summary: {
          open: tickets.filter((ticket) => ticket.status === 'open').length,
          in_progress: tickets.filter((ticket) => ticket.status === 'in_progress').length,
        },
      })),
    });
  });

  await page.route('**/api/admin/support-requests/*', async (route: Route) => {
    if (route.request().method() !== 'PATCH') {
      await route.fallback();
      return;
    }
    const requestId = decodeURIComponent(route.request().url().split('/').pop() || '');
    const payload = route.request().postDataJSON() as { status: TicketFixture['status']; admin_note: string };
    let updated: TicketFixture | undefined;
    tickets = tickets.map((ticket) => {
      if (ticket.request_id !== requestId) return ticket;
      updated = { ...ticket, status: payload.status, admin_note: payload.admin_note, updated_at: '2026-07-12T07:00:00Z' };
      return updated;
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope({ request: updated })),
    });
  });

  return {
    getRequestCount: () => requestCount,
    failRequestForQuery: (query: string) => { failQuery = query; },
  };
}

test('ticket queue persists filters and focus while retaining usable results on failure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const mocks = await installSupportQueueMocks(page);
  await page.goto('/admin/support-requests');

  await expect(page.getByRole('heading', { name: /Customer ticket queue|客户工单队列/i })).toBeVisible();
  await expect(page.locator('[data-ui="support-request-queue-item"]')).toHaveCount(4);
  await expect(page.locator('table')).toHaveCount(0);
  expect(mocks.getRequestCount()).toBe(1);

  const rows = page.locator('[data-ui="support-request-queue-item"]');
  await expect(rows.nth(0)).toContainText('Payment confirmation is still missing');
  await expect(rows.nth(1)).toContainText('Site connection needs review');
  await expect(rows.nth(2)).toContainText('Usage total needs explanation');
  await expect(page.locator('#support-request-inspector')).toContainText('Payment confirmation is still missing');

  await page.getByRole('button', { name: /^Open$|^待处理$/i }).click();
  await expect(page).toHaveURL(/status=open/);
  await expect(rows).toHaveCount(2);

  await page.getByLabel(/Search tickets|搜索工单/i).fill('Payment');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/q=Payment/);
  await expect(rows).toHaveCount(1);

  const inspectButton = page.getByRole('button', { name: /^Inspect$|^检查$/i });
  await inspectButton.focus();
  await inspectButton.press('Enter');
  await expect(page).toHaveURL(/focus=sr_overdue_payment/);
  await page.reload();
  await expect(page.getByLabel(/Search tickets|搜索工单/i)).toHaveValue('Payment');
  await expect(page.locator('#support-request-inspector')).toContainText('Payment confirmation is still missing');

  mocks.failRequestForQuery('Missing');
  await page.getByLabel(/Search tickets|搜索工单/i).fill('Missing');
  await page.getByRole('button', { name: /^Apply$|^应用$/i }).click();
  await expect(page).toHaveURL(/q=Missing/);
  await expect(page.getByText(/last successfully loaded page|最近一次成功加载的页面/i)).toBeVisible();
  await expect(rows).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('ticket inspector separates customer submission from bounded internal handling', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installSupportQueueMocks(page);
  await page.goto('/admin/support-requests');

  const inspector = page.locator('#support-request-inspector');
  await expect(inspector.getByRole('heading', { name: /Customer submission|客户提交内容/i })).toBeVisible();
  await expect(inspector.getByRole('heading', { name: /Internal handling|内部处理/i })).toBeVisible();
  await expect(page.locator('textarea')).toHaveCount(1);

  const statusSelect = inspector.getByRole('combobox', { name: /^Status$|^状态$/i });
  await statusSelect.selectOption('in_progress');
  await inspector.getByLabel(/Internal handling note|内部处理备注/i).fill('Provider confirmation is being reconciled.');
  await inspector.getByRole('button', { name: /Update ticket|更新工单/i }).click();

  await expect(page.getByText(/Ticket updated|工单已更新/i).first()).toBeVisible();
  await expect(statusSelect).toHaveValue('in_progress');
  await expect(inspector.getByLabel(/Internal handling note|内部处理备注/i)).toHaveValue('Provider confirmation is being reconciled.');
  await expect(inspector.getByRole('link', { name: /Open conversation|打开会话/i })).toHaveAttribute('href', '/admin/support-requests/sr_overdue_payment');
});
