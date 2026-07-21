import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const planPage = readFileSync(resolve(root, 'src/app/admin/plans/[planId]/page.tsx'), 'utf8');
const i18n = readFileSync(resolve(root, 'src/lib/i18n.ts'), 'utf8');

assert.match(
  planPage,
  /sales_price_cny[\s\S]*max_cost_per_period/,
  'Admin package editor must keep sales price and model cost budget as separate values'
);
assert.match(
  planPage,
  /sales_price_cny_detail[\s\S]*model_cost_budget_usd_detail/,
  'Admin package editor must explain customer price and internal cost-budget purposes'
);
assert.match(
  planPage,
  /sales_price_cny: Number\(form\.sales_price_cny/,
  'Admin package publish request must send the customer-facing sales price'
);
assert.match(
  i18n,
  /销售价格（人民币\/30天）[\s\S]*模型成本预算（美元\/周期）/,
  'Chinese admin copy must label the two currencies and purposes honestly'
);

console.log('admin_plan_pricing_contract: ok');
