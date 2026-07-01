import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const troubleshootingKeys = Array.from(
  pageSource.matchAll(/(?:titleKey|descKey|actionKey|groupKey):\s*['`](admin\.[a-z0-9_.]+)['`]/g)
)
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(
  troubleshootingKeys.length >= 17,
  'Advanced troubleshooting cards must declare i18n keys for title, description, action, and group copy'
);

for (const key of troubleshootingKeys) {
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
  /'admin\.nav_agent_feedback': 'Agent 反馈质量'/,
  'Agent Feedback advanced card title must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.advanced\.action_view_agent_feedback': '查看质量反馈'/,
  'Agent Feedback advanced card action must provide Simplified Chinese copy'
);
