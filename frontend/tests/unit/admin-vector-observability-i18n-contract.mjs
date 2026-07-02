import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/vector-observability/page.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const vectorKeys = Array.from(pageSource.matchAll(/['`](admin\.vector_obs\.[a-z0-9_]+)['`]/g))
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(vectorKeys.length > 20, 'Vector observability page must route visible copy through vector_obs i18n keys');

for (const key of vectorKeys) {
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
  /'admin\.vector_obs\.title': '向量观测'/,
  'Vector Observability must provide a Simplified Chinese page title'
);

assert.match(
  i18nSource,
  /'admin\.vector_obs\.empty_checks_title': '只读排查项'/,
  'Vector Observability empty state must provide localized read-only checks'
);

assert.match(
  i18nSource,
  /'common\.apply': '应用'/,
  'The shared Apply button label must provide Simplified Chinese copy'
);

assert.doesNotMatch(
  pageSource,
  /detail:\s*data\.health\.summary/,
  'Vector Observability must not render backend English health summary directly'
);

assert.doesNotMatch(
  pageSource,
  /onClick=\{[^}]*sync|onClick=\{[^}]*repair|onClick=\{[^}]*reindex/i,
  'Vector Observability must stay read-only and must not add sync, repair, or reindex actions'
);
