import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/audio-workbench/page.tsx');
const pageSource = readFileSync(pagePath, 'utf8');

assert.match(
  pageSource,
  /type AudioWorkbenchFailureData = \{[\s\S]*?action\?: AudioWorkbenchFailureAction \| string;[\s\S]*?retry_attempted\?: boolean;[\s\S]*?retryable\?: boolean;/,
  'audio workbench must model backend failure diagnostics instead of displaying only a raw error string'
);

assert.match(
  pageSource,
  /function buildFailureNotice\(payload: unknown, fallback: string\): AudioWorkbenchNotice/,
  'audio workbench must normalize backend error envelopes before rendering failure copy'
);

assert.match(
  pageSource,
  /activeNotice\.data\.action === 'retry_or_use_narration'/,
  'audio workbench must expose the summary fallback path when the backend recommends narration'
);

assert.match(
  pageSource,
  /href="\/admin\/ai-resources"/,
  'audio workbench must provide a direct AI resources action for provider or profile configuration failures'
);

assert.match(
  pageSource,
  /onClick=\{\(\) => void createJob\(\)\}/,
  'audio workbench must provide an explicit retry action for retryable failures'
);

assert.match(
  pageSource,
  /Script attempts: \{job\.script\.generation\.attempts\}/,
  'audio workbench must surface summary script retry evidence in the result inspector'
);

assert.match(
  pageSource,
  /Trace: \{activeNotice\.data\.trace_id\}/,
  'audio workbench failure notices must expose trace evidence for operator debugging'
);

assert.match(
  pageSource,
  /Model: \{activeNotice\.data\.provider_id \|\| 'provider'\} \/ \{activeNotice\.data\.model_id \|\| 'model'\}/,
  'audio workbench failure notices must expose provider and model evidence'
);

assert.match(
  pageSource,
  /No direct WordPress write\./,
  'audio workbench must continue to present generated audio as a candidate-only artifact'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/audio-jobs\/recent\?limit=10'/,
  'audio workbench must load a bounded recent-runs projection instead of creating a separate audio job store'
);

assert.match(
  pageSource,
  /Last 10 Admin audio runtime records/,
  'audio workbench recent runs copy must present the list as runtime evidence, not a media library'
);

assert.match(
  pageSource,
  /onClick=\{\(\) => void loadJob\(recent\.run_id\)\}/,
  'audio workbench recent runs must inspect existing run detail instead of exposing direct media management actions'
);

console.log('admin_audio_workbench_contract: ok');
