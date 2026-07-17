import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/app/admin/media-observability/page.tsx'),
  'utf8'
);
const metadataPanelSource = readFileSync(
  resolve(process.cwd(), 'src/components/backoffice/CloudWorkflowMetadataPanel.tsx'),
  'utf8'
);
const portalClientSource = readFileSync(resolve(process.cwd(), 'src/lib/portal-client.ts'), 'utf8');
const portalPanelSource = readFileSync(
  resolve(process.cwd(), 'src/components/portal/PortalMediaProcessingPanel.tsx'),
  'utf8'
);
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

const mediaKeys = Array.from(pageSource.matchAll(/['`](admin\.media_obs\.[a-z0-9_]+)['`]/g))
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

assert.ok(mediaKeys.length > 30, 'Media observability page must route visible copy through media_obs i18n keys');

const workflowKeys = Array.from(metadataPanelSource.matchAll(/['`](workflow_metadata\.[a-z0-9_.]+)['`]/g))
  .map((match) => match[1])
  .filter((key, index, keys) => keys.indexOf(key) === index)
  .sort();

const requiredWorkflowKeys = [
  ...workflowKeys,
  'workflow_metadata.workflow.media_derivative_artifact_generation.title',
  'workflow_metadata.workflow.media_derivative_artifact_generation.summary',
  'workflow_metadata.badge.whole_run_offload',
  'workflow_metadata.badge.write_blocked',
  'workflow_metadata.handoff_owner.wordpress_local',
  'workflow_metadata.fail_closed_behavior.return_artifact_unavailable',
  'workflow_metadata.execution_pattern.whole_run_offload',
  'workflow_metadata.storage_mode.short_ttl_artifact',
  'workflow_metadata.step.validate_media_derivative_request',
  'workflow_metadata.step.queue_runtime_worker_job',
  'workflow_metadata.step.process_static_image_derivative',
  'workflow_metadata.step.store_short_ttl_artifact',
  'workflow_metadata.step.return_artifact_reference_for_local_review',
  'workflow_metadata.stop_condition.invalid_source',
  'workflow_metadata.stop_condition.unsupported_format',
  'workflow_metadata.stop_condition.artifact_ttl_expired',
  'workflow_metadata.stop_condition.local_approval_required',
].filter((key, index, keys) => keys.indexOf(key) === index);

for (const key of [...mediaKeys, ...requiredWorkflowKeys, 'common.updated_at']) {
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
  /'admin\.media_obs\.title': '媒体处理观测'/,
  'Media Observability must provide a Simplified Chinese page title'
);

assert.match(
  i18nSource,
  /'workflow_metadata\.workflow\.media_derivative_artifact_generation\.title': '媒体衍生工件生成'/,
  'Media workflow metadata must provide a Simplified Chinese title'
);

assert.doesNotMatch(
  pageSource,
  /detail:\s*data\.health\.summary/,
  'Media Observability must not render backend English health summary directly'
);

assert.doesNotMatch(
  `${pageSource}\n${portalClientSource}\n${portalPanelSource}`,
  /artifactDownloadCount|artifact_download_count|admin\.media_obs\.downloads|\bdownloads\b/i,
  'Media Observability must not retain the retired derivative download counter'
);

for (const field of [
  'delivery_started_count',
  'delivery_stream_completed_count',
  'delivery_acknowledged_count',
  'stream_completion_rate',
  'acknowledgement_rate',
]) {
  assert.match(pageSource, new RegExp(field), `${field} must be projected into the admin UI`);
  assert.match(
    portalClientSource,
    new RegExp(field),
    `${field} must be declared in the portal client contract`
  );
}

assert.match(
  portalPanelSource,
  /delivery_stream_completed_count[\s\S]*delivery_acknowledged_count/,
  'Portal media panel must show stream completion and verified receipt evidence'
);

assert.doesNotMatch(
  pageSource,
  />\s*Filter\s*</,
  'Media Observability filter action must use localized shared Apply copy'
);

assert.doesNotMatch(
  metadataPanelSource,
  />\s*(Workflow metadata|Write posture|Review posture|Technical metadata|No metadata declared\.)\s*</,
  'Workflow metadata panel labels must use localized copy'
);
