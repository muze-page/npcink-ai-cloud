# Media Derivative Operations Runbook v1

Status: active Cloud guidance; WordPress end-to-end smoke pending connector adoption
Date: 2026-06-03

## Scope

This runbook covers Cloud-side `media_job_request.v1` image processing through
the versioned `image.transform.v1` operation.

Cloud remains a runtime service only. It produces temporary derivative
artifacts and bounded processing evidence. WordPress writes, attachment
metadata changes, replacement decisions, proposal approval, preflight, audit,
and rollback authority stay in the local WordPress/Core path.

## Runtime Flow

1. A local host/addon streams one `media_upload_request.v1` multipart request
   to `POST /v1/runtime/media/uploads` using one `request` field and one `file`.
2. Cloud validates the source and returns a same-site temporary source
   `artifact_id` with operation `image.upload.v1`.
3. The host submits `media_job_request.v1` to `POST /v1/runtime/media/jobs`
   with that source ID, optional separately uploaded watermark artifact ID,
   strict transform parameters, and `operation=image.transform.v1`.
4. Cloud checks artifact ownership, lifecycle, remaining TTL, format,
   dimensions, quality, result TTL, crop, and watermark intent, then queues a
   normal runtime worker job using the existing FastAPI,
   Postgres, Redis, and worker stack.
5. The worker produces a short-lived derivative artifact and a
   `media_derivative_job_metrics` row.
6. The local host/addon previews the derivative through its own controlled
   signed proxy.
7. Core receives a proposal payload and remains the only approval and
   WordPress write owner.
8. Cloud exposes read-only admin/portal observability for processing health.

The workflow display metadata for this flow is sourced from the Cloud read-only
Agent/Workflow metadata projection as `media_derivative_artifact_generation`.
Runtime artifact data and approval/write decisions remain outside that
projection.

## Supported Inputs And Outputs

Supported source media type:

- `image`

Supported target formats:

- `webp`
- `avif`
- `jpeg`
- `png`
- `original`

Supported options:

- `max_width`: `1..10000`
- `quality`: `1..100`
- upload `ttl_minutes` and job `result_ttl_minutes`: `15..60`
- `crop`: optional aspect-ratio crop, for example
  `{"type":"aspect_ratio","aspect_ratio":"16:9","position":"center"}`
- watermark image: same-site temporary artifact from a separate upload

Unsupported behavior:

- animated image processing;
- video or document processing;
- permanent Cloud media registry;
- WordPress attachment metadata updates from Cloud;
- Cloud-side approval or apply decisions.

## Deployment Checklist

Before enabling the feature:

1. Deploy the API and worker from the same revision.
2. Run migrations:

   ```bash
   docker exec npcink-ai-cloud-api-1 alembic upgrade head
   ```

3. Confirm these migrations are present:

   - `20260603_0036_media_derivative_job_metrics`
   - `20260714_0061_local_volume_artifact_store`

4. Restart the runtime worker after migration:

   ```bash
   docker restart npcink-ai-cloud-worker-1
   ```

5. After the WordPress connector adopts both resources, run the WordPress smoke:

   ```bash
   pnpm run smoke:media-derivative:wp
   ```

Until that connector batch lands, this smoke is not current P3-B3A acceptance
evidence. Expected future smoke evidence:

- local batch planning returns a candidate with Cloud request input and a
  `batch_size_recommendation`;
- derivative preview succeeds;
- Core proposal is created and approved;
- attachment URL changes after adoption;
- page hard-coded references no longer contain the old URL;
- option/theme-mod reference repair succeeds;
- rollback history is present;
- `media_derivative_job_metrics` contains the succeeded run;
- `media_artifacts` contains an available short-lived artifact with
  `operation = 'image.transform.v1'`; bytes live in the shared ArtifactStore
  volume rather than PostgreSQL.

## Observability

Admin route:

- `/internal/service/admin/media-observability`

Portal route:

- `/portal/v1/sites/{site_id}/media-observability`

Primary fields:

- `jobs_total`
- `succeeded_total`
- `failed_total`
- `success_rate`
- `avg_processing_duration_ms`
- `p95_processing_duration_ms`
- `avg_queue_wait_ms`
- `source_bytes_total`
- `output_bytes_total`
- `bytes_saved_total`
- `active_artifact_count`
- `active_artifact_bytes`
- `artifact_download_count`
- `watermark_job_count`

Operator interpretation:

- `failed_total > 0`: inspect `errors` and `recent_failures`.
- Low `success_rate`: check unsupported formats, decode failures, oversized
  uploads, and animated inputs.
- High `p95_processing_duration_ms`: check source dimensions, worker CPU, and
  queue pressure.
- High `active_artifact_bytes`: verify cleanup worker cadence and TTL bounds.
- Low `artifact_download_count`: preview proxy or local adoption flow may not
  be fetching the derivative.

Portal responses are site-scoped and omit cross-site `sites` breakdown.

## Error Catalog

Common request-time errors:

| Error code | Meaning | Operator action |
| --- | --- | --- |
| `media_upload.invalid_request` | Missing or invalid upload multipart/JSON | Check host/addon request builder |
| `media_upload.ingress_unavailable` | Temporary ingress storage failed | Check local disk capacity and I/O |
| `media_upload.upload_too_large` | Upload exceeds byte limits | Downscale locally before upload |
| `media_job.validation_error` | Invalid versioned job contract or parameters | Check host/addon job builder |
| `media_job.source_artifact_not_found` | Source is missing or cross-site | Upload the source for this site |
| `media_job.source_artifact_expired` | Source has insufficient remaining TTL | Upload the source again |
| `media_job.source_artifact_unavailable` | Stored source bytes failed verification/read | Regenerate the source and inspect storage |
| `media_job.watermark_artifact_not_found` | Watermark is missing or cross-site | Upload the watermark for this site |
| `media_job.watermark_artifact_expired` | Watermark has insufficient remaining TTL | Upload the watermark again |
| `media_job.watermark_artifact_unavailable` | Stored watermark bytes failed verification/read | Regenerate the watermark and inspect storage |
| `media_derivative.site_queue_full` | Site queue admission is saturated | Retry after current jobs finish |

Common worker-result errors:

| Error code | Meaning | Operator action |
| --- | --- | --- |
| `media_derivative.source_decode_failed` | Image could not be decoded | Ask local flow to skip or show source unsupported |
| `media_derivative.source_too_large` | Pixel-count safety guard rejected the image | Skip or downscale locally first |
| `media_derivative.animated_source_unavailable` | Animated input is intentionally not processed | Skip animated formats |
| `media_derivative.format_unavailable` | Runtime Pillow build cannot encode target format | Use another format or deploy a runtime with encoder support |
| `media_derivative.processing_failed` | Unexpected processing failure | Inspect logs for run id and source characteristics |

Download-time errors:

| Error code | Meaning | Operator action |
| --- | --- | --- |
| `media_derivative.artifact_not_found` | Artifact id is unknown for the site | Regenerate preview |
| `media_derivative.artifact_expired` | Artifact TTL has elapsed | Regenerate preview before proposing/adopting |

## Compatibility Notes

Expected behavior:

- EXIF orientation is applied before crop, resize, and output.
- Aspect-ratio crop runs before max-width resize and records a processing
  warning when pixels are cropped.
- CMYK or palette-like inputs are converted to web-safe output modes when
  needed.
- JPEG output flattens alpha and records a warning.
- Every output, including `original`, always re-encodes through Pillow so
  EXIF/GPS/ICC metadata is not passed through. `original` preserves a supported
  still-image format when possible.
- Upload and worker decode admission is capped at 8,192 pixels per axis and
  16,777,216 pixels total, equivalent to one 64 MiB RGBA decode surface before
  crop, resize, watermark, and encoder buffers.
- Animated sources are rejected instead of silently flattening the first frame.

## Production Guardrails

- Keep artifact TTL between 15 and 60 minutes.
- Do not expose artifact blob data in admin or portal observability.
- Do not return WordPress write decisions from Cloud responses.
- Do not add a Cloud media registry or Cloud ability registry.
- Do not replace the current FastAPI, Postgres, Redis, worker architecture with
  Temporal, Celery, RabbitMQ, Kafka, or Kubernetes-first infrastructure.
