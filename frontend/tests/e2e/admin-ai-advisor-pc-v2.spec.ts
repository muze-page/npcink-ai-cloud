import { expect, test } from '@playwright/test';
import {
  buildAdminApiEnvelope,
  installAdminMocks,
} from './helpers/admin-operator-fixture';

const advisorBranch = {
  generation: { mode: 'rule', cache_status: 'miss' },
  scope: 'operations_analysis',
  headline: 'Provider reliability needs review',
  operator_summary: 'Provider errors or fallback pressure are present in recent traffic.',
  operator_next_step: 'inspect_provider_errors_latency_and_fallbacks',
  severity: 'warning',
  status: 'attention',
  source_context: {
    advisor: {
      scope: 'operations_analysis',
      status: 'attention',
      severity: 'warning',
      summary: 'Provider errors or fallback pressure are present in recent traffic.',
      confidence: 'high',
      evidence: [
        { kind: 'admin_overview', ref: '/internal/service/admin/overview', label: 'commercial coverage and usage summary' },
        { kind: 'runtime_diagnostics', ref: '/internal/service/runtime/diagnostics/summary', label: 'runtime queue, callback, and guard summary' },
        { kind: 'site_knowledge_observability', ref: '/internal/service/site-knowledge/observability/summary', label: 'knowledge search and index health summary' },
        { kind: 'provider_call_records', ref: 'provider_call_records', label: 'provider call metrics aggregated from run telemetry' },
      ],
      recommended_actions: [
        { action: 'inspect_provider_errors_latency_and_fallbacks', requires_operator: true },
      ],
      signals: [
        { code: 'ops.runtime_quality', total_runs: 370, failed_runs: 43, run_failure_rate: 0.116, guard_events: 2 },
        { code: 'ops.provider_quality', provider_calls: 460, provider_errors: 83, provider_error_rate: 0.18 },
        { code: 'ops.knowledge_quality', knowledge_searches: 23, knowledge_no_hits: 0, knowledge_no_hit_rate: 0 },
        { code: 'ops.usage_cost', usage_events: 2829, provider_cost: 0 },
      ],
      drilldown: {},
    },
  },
};

async function installAdvisorMocks(page: Parameters<typeof installAdminMocks>[0]) {
  const requestedPaths: string[] = [];
  await installAdminMocks(page);
  await page.unroute('**/api/admin/**');
  await page.route('**/api/admin/advisor/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    requestedPaths.push(pathname);
    const data = pathname.endsWith('/ops-summary-preview')
      ? {
          preview_version: 'v1',
          baseline: advisorBranch,
          ai: advisorBranch,
          comparison: { baseline_mode: 'rule', ai_mode: 'rule', ai_used: false, ai_called: false, cache_hit: false, tokens_in: 0, tokens_out: 0, request_cost: 0 },
          safety: { wordpress_write_allowed: false, requires_operator_review: true },
        }
      : pathname.endsWith('/ops-summary-value')
        ? { window: { days: 7 }, totals: {}, rates: {}, value_signal: {}, recent_events: [] }
        : { items: [] };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildAdminApiEnvelope(data)),
    });
  });
  return requestedPaths;
}

test('Operations Advisor keeps the current PC diagnosis primary and technical AI metrics advanced', async ({ page }, testInfo) => {
  const requestedPaths = await installAdvisorMocks(page);
  await page.goto('/admin/ai-advisor');

  const diagnosis = page.locator('[data-ui="advisor-current-diagnosis"]');
  await expect(diagnosis.getByRole('heading', { name: /提供方可靠性需要检查|Provider reliability needs review/i })).toBeVisible();
  await expect(diagnosis.getByText(/近期流量中存在提供方错误或回退压力|Provider errors or fallback pressure/i)).toBeVisible();
  await expect(diagnosis.getByText(/商业覆盖与用量摘要|Commercial coverage and usage summary/i)).toBeVisible();
  await expect(diagnosis.getByText(/运行队列、回调与防护摘要|Runtime queue, callback, and guard summary/i)).toBeVisible();

  const advanced = page.locator('details').filter({ hasText: /高级评估参数|Advanced evaluation parameters/i });
  await expect(advanced).not.toHaveAttribute('open', '');
  await expect(advanced.getByText(/^AI 参与$|^AI participation$/i).first()).toBeHidden();
  await expect(advanced.getByText(/^请求成本$|^Request cost$/i).first()).toBeHidden();
  await expect(page.getByRole('button', { name: /运行诊断|Run diagnosis/i })).toBeVisible();

  expect(requestedPaths).toEqual(['/api/admin/advisor/ops-summary-preview']);

  const evaluationDetails = page.locator('details').filter({
    hasText: /AI evaluation details|AI 评估详情/i,
  });
  await evaluationDetails.locator('summary').click();
  await expect.poll(() => requestedPaths.sort()).toEqual([
    '/api/admin/advisor/ops-summary-history',
    '/api/admin/advisor/ops-summary-preview',
    '/api/admin/advisor/ops-summary-value',
  ]);
  await testInfo.attach('p4-e03-admin-advisor-readonly', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
});
