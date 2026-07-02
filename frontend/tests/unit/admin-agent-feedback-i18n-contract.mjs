import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/agent-feedback/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const agentFeedbackKeys = Array.from(
  pageSource.matchAll(/['`](admin\.agent_feedback\.[a-z0-9_]+)['`]/g)
)
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(
  agentFeedbackKeys.length > 50,
  'Agent Feedback page must route visible copy through agent_feedback i18n keys'
);

for (const key of agentFeedbackKeys) {
  assert.match(
    enSource,
    new RegExp(`'${key.replaceAll('.', '\\.')}':`),
    `${key} must exist in the English translation dictionary`
  );
  assert.match(
    zhSource,
    new RegExp(`'${key.replaceAll('.', '\\.')}':`),
    `${key} must exist in the Simplified Chinese translation dictionary`
  );
}

assert.match(
  i18nSource,
  /'admin\.agent_feedback\.title': 'Agent 反馈质量'/,
  'Agent Feedback must provide a Simplified Chinese page title'
);

assert.match(
  i18nSource,
  /'admin\.agent_feedback\.boundary_desc': '此页面只汇总元数据反馈/,
  'Agent Feedback boundary copy must be localized'
);

assert.doesNotMatch(
  pageSource,
  />\s*(Runtime|Surface|Events|Accepted|Evidence weak|Wrong step|Top labels)\s*</,
  'Agent Feedback table headings must use localized copy'
);

assert.doesNotMatch(
  pageSource,
  /`Limited to \$\{formatNumber\(data\.maxEvents\)\} events`|`\$\{data\.windowHours\}h window`/,
  'Agent Feedback metric details must use localized copy'
);

assert.doesNotMatch(
  pageSource,
  />\s*(Accepted|Rejected|Evidence|Wrong step)\s*\{formatNumber\(point\./,
  'Agent Feedback trend labels must use localized copy'
);
