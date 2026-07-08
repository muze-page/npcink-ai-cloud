# Media Derivative Operations Runbook v1

Status: active guidance
Date: 2026-06-03

## Scope

This runbook covers Cloud-side media derivative processing for
`generate_optimized_media_derivative`.

Cloud remains a runtime service only. It produces temporary derivative
artifacts and bounded processing evidence. WordPress writes, attachment
metadata changes, replacement decisions, proposal approval, preflight, audit,
and rollback authority stay in the local WordPress/Core path.

## Runtime Flow

1. A local host/addon submits `media_derivative_cloud_request.v1` to Cloud.
2. The request provides a source image as `source_file` upload or a same-site
   temporary artifact reference.
3. Cloud validates format, dimensions, quality, TTL, source size, source media
   type, optional aspect-ratio crop intent, and optional watermark source.
4. Cloud queues a normal runtime worker job using the existing FastAPI,
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
- `ttl_minutes`: `15..60`
- `crop`: optional aspect-ratio crop, for example
  `{"type":"aspect_ratio","aspect_ratio":"16:9","position":"center"}`
- watermark image: uploaded `watermark_file` or same-site temporary artifact

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

   - `20260602_0034_media_derivative_artifacts`
   - `20260603_0036_media_derivative_job_metrics`

4. Restart the runtime worker after migration:

   ```bash
   docker restart npcink-ai-cloud-worker-1
   ```

5. Run the WordPress smoke:

   ```bash
   pnpm run smoke:media-derivative:wp
   ```

Expected smoke evidence:

- local batch planning returns a candidate with Cloud request input and a
  `batch_size_recommendation`;
- derivative preview succeeds;
- Core proposal is created and approved;
- attachment URL changes after adoption;
- page hard-coded references no longer contain the old URL;
- option/theme-mod reference repair succeeds;
- rollback history is present;
- `media_derivative_job_metrics` contains the succeeded run;
- `media_derivative_artifacts` contains the short-lived artifact.

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
| `media_derivative.invalid_request` | Missing or invalid request JSON | Check host/addon request builder |
| `media_derivative.invalid_format` | Unsupported target format | Use `webp`, `avif`, `jpeg`, `png`, or `original` |
| `media_derivative.source_media_type_unavailable` | Unsupported media type | Send images only |
| `media_derivative.invalid_source` | No source or conflicting source mode | Send exactly one source mode |
| `media_derivative.invalid_crop` | Invalid crop type, aspect ratio, or position | Use bounded aspect-ratio crop options |
| `media_derivative.invalid_watermark` | Missing/conflicting watermark source or invalid watermark options | Send options plus exactly one watermark source |
| `media_derivative.upload_too_large` | Source or watermark exceeds upload byte limit | Let local flow skip or downscale before upload |
| `media_derivative.source_artifact_not_found` | Referenced source artifact missing, expired, or cross-site | Regenerate source artifact |
| `media_derivative.watermark_artifact_not_found` | Referenced watermark artifact missing, expired, or cross-site | Regenerate watermark artifact |

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
- `original` without crop or watermark preserves source bytes and dimensions.
- `original` with crop or watermark re-encodes through a supported still-image
  format.
- Animated sources are rejected instead of silently flattening the first frame.

## Production Guardrails

- Keep artifact TTL between 15 and 60 minutes.
- Do not expose artifact blob data in admin or portal observability.
- Do not return WordPress write decisions from Cloud responses.
- Do not add a Cloud media registry or Cloud ability registry.
- Do not replace the current FastAPI, Postgres, Redis, worker architecture with
  Temporal, Celery, RabbitMQ, Kafka, or Kubernetes-first infrastructure.
