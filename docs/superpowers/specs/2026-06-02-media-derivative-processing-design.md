# Media Derivative Processing Service — Design Spec

Date: 2026-06-02
Status: Approved

## Overview

Implement a Cloud-side media derivative processing service within the existing runtime plane. The service generates optimized image derivatives (format conversion, resizing) via the existing FastAPI + worker + Postgres + Redis infrastructure.

## Constraints

- **Scope**: Runtime/service enhancement only
- **No WordPress**: No WordPress write fields, attachment metadata, or write policies in any request or response
- **No new control plane**: No media registry, ability registry, or approval truth
- **No new infrastructure**: No Temporal, Celery, RabbitMQ, Kafka, or K8s-first patterns
- **Artifact is ephemeral**: Short TTL (15-60 min), not canonical truth, must be purgeable

## Architecture Choice

Approach A: Minimal intrusion — add a branch in `_execute_existing_run()`, but do not route media derivative jobs through provider/model routing.

- Reuse `run_records`, Redis runtime queue, `RuntimeService.process_queued_runs()`
- Reuse `authorize_public_request(required_scope="runtime:execute")`
- Results delivered via existing `GET /v1/runs/{run_id}/result`

### Runtime Entry Point

The media derivative endpoint MUST NOT call `RuntimeService.execute()` directly. The existing `execute()` path resolves a routing profile before run creation, and routing profiles are model/provider oriented. Media derivative processing is a Cloud worker service job, not a hosted model provider call.

Add a dedicated helper, for example:

```python
def enqueue_media_derivative_run(request: MediaDerivativeRunRequest) -> RuntimeExecutionResponse:
```

This helper reuses the same runtime primitives as `execute()`:

- active site check
- commercial runtime authorization
- idempotency conflict handling
- `run_records` creation
- encrypted queued input storage
- Redis queue signal publication
- runtime result and status read paths

It bypasses:

- `RoutingService.resolve()`
- provider candidate selection
- provider fallback
- `ProviderCallRecord` creation

The helper writes a `RunRecord` with:

- `execution_kind = "media_derivative"`
- `ability_name = "generate_optimized_media_derivative"`
- `ability_family = "vision"`
- `execution_pattern = "whole_run_offload"`
- `profile_id = "media_derivative.worker"`
- `selected_provider_id = "media_derivative"`
- `selected_model_id = "pillow"`
- `selected_instance_id = "cloud-worker"`

These selected fields are deterministic service identifiers for existing runtime response compatibility only. They do not create a provider registry, model catalog entry, media registry, or second routing truth.

## Data Model

### Table: `media_derivative_artifacts`

```sql
CREATE TABLE media_derivative_artifacts (
    artifact_id      VARCHAR(191) PRIMARY KEY,
    run_id           VARCHAR(191) NOT NULL REFERENCES run_records(run_id),
    site_id          VARCHAR(191) NOT NULL,
    storage_ref      VARCHAR(512) NOT NULL,
    blob_data        BYTEA NOT NULL,
    mime_type        VARCHAR(64) NOT NULL,
    format           VARCHAR(16) NOT NULL,
    width            INTEGER NOT NULL DEFAULT 0,
    height           INTEGER NOT NULL DEFAULT 0,
    filesize_bytes   INTEGER NOT NULL DEFAULT 0,
    checksum         VARCHAR(128) NOT NULL,
    source_media_type VARCHAR(16) NOT NULL DEFAULT 'image',
    processing_warnings_json JSON,
    expires_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    purged_at        TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mda_run_id ON media_derivative_artifacts(run_id);
CREATE INDEX idx_mda_site_id ON media_derivative_artifacts(site_id);
CREATE INDEX idx_mda_expires_at ON media_derivative_artifacts(expires_at)
    WHERE purged_at IS NULL;
```

Key decisions:

- Table name is `media_derivative_artifacts`, not `media_registry`
- `blob_data BYTEA` stores file binary for the MVP stage; `storage_ref` uses `blob://media_derivative/{artifact_id}` format, preserving abstraction for future S3 migration
- `source_media_type` defaults to `image`; video requests return 422
- `expires_at` default TTL is 30 minutes (within 15-60 min range)
- `purged_at` marks logical deletion by the cleanup worker
- No WordPress write fields exist anywhere in the schema

SQLAlchemy model `MediaDerivativeArtifact` goes in `app/core/models.py` alongside `RunRecord` and `ProviderCallRecord`.

## Request Contract

### Endpoint

`POST /v1/runtime/media-derivatives`

Auth: `authorize_public_request(required_scope="runtime:execute")` with the media-specific public body limit described below.

### Two Source Modes

| Mode | Fields | Description |
|------|--------|-------------|
| **Multipart** | `request`: JSON string + `source_file`: UploadFile | Upload image source file |
| **JSON** | Body is JSON, `source.artifact_id` references existing artifact | Reference a previously uploaded artifact |

Exactly one source mode is allowed:

- Multipart requests MUST include `source_file` and MUST NOT include `source.artifact_id`.
- JSON artifact-reference requests MUST include `source.artifact_id` and MUST NOT include `source_file`.
- Referenced artifacts MUST be queried by both `artifact_id` and `auth.site_id`.
- Referenced artifacts MUST have `purged_at IS NULL` and `expires_at > now`.
- A missing, expired, purged, or cross-site artifact reference returns 404 for the request path to avoid artifact enumeration across sites.

### Public Auth and Large Body Handling

The public auth layer currently signs and validates the full request body. The media derivative multipart endpoint therefore needs an explicit large-body auth contract instead of relying on the default runtime body limit.

For this MVP:

- `POST /v1/runtime/media-derivatives` still uses standard HMAC canonical request signing.
- The signed body digest is the SHA-256 digest of the exact raw multipart request body.
- The endpoint uses a media-specific public body limit of `MAX_UPLOAD_BYTES_IMAGE + 1 MiB` to account for multipart framing and JSON metadata.
- Requests above that media-specific limit return 413 `media_derivative.upload_too_large`.
- The implementation MUST NOT skip HMAC signing for multipart uploads.
- The implementation MUST NOT sign only the JSON `request` part while leaving `source_file` unsigned.

If this cannot be implemented cleanly in `authorize_public_request`, split upload into a separate pre-upload endpoint before implementing this API. Do not silently reduce `MAX_UPLOAD_BYTES_IMAGE` to the default public runtime body limit.

### Request Schema

```json
{
  "request_contract_version": "media_derivative_cloud_request.v1",
  "cloud_job_payload": {
    "job_type": "generate_optimized_media_derivative",
    "target_format": "webp",
    "max_width": 1200,
    "quality": 82,
    "source_media_type": "image"
  },
  "source": {
    "artifact_id": "art_..."
  },
  "ttl_minutes": 30
}
```

### Constants

```python
ALLOWED_TARGET_FORMATS = frozenset({"webp", "avif", "jpeg", "png", "original"})
ALLOWED_SOURCE_MEDIA_TYPES = frozenset({"image"})
MAX_UPLOAD_BYTES_IMAGE = 50 * 1024 * 1024   # 50 MB
ARTIFACT_DEFAULT_TTL_MINUTES = 30
ARTIFACT_MIN_TTL_MINUTES = 15
ARTIFACT_MAX_TTL_MINUTES = 60

BLOCKED_RESPONSE_FIELDS = frozenset({
    "wordpress_write_policy", "wordpress_write_target",
    "attachment_metadata", "metadata_patch", "replace_file",
    "apply_decision", "approval_decision", "target_attachment_id",
})
```

### Validation Order

1. `request_contract_version` must equal `"media_derivative_cloud_request.v1"` — 400
2. Exactly one source mode must be present — 400 `media_derivative.invalid_source`
3. `source_media_type` must be `"image"` — video returns 422 `media_derivative.source_media_type_unavailable`
4. `target_format` must be in `ALLOWED_TARGET_FORMATS` — gif returns 422 `media_derivative.invalid_format`
5. `quality` range 1-100, `max_width` range 1-10000 — 422
6. `ttl_minutes` range 15-60 — 422
7. Multipart upload size > 50MB — 413 `media_derivative.upload_too_large`
8. Referenced artifact is missing, expired, purged, or cross-site — 404 `media_derivative.source_artifact_not_found`
9. Response and `result_json` must not contain any `BLOCKED_RESPONSE_FIELDS` key

### Internal RunRecord Construction

The endpoint converts the request into a media derivative run request and passes it to the dedicated runtime helper. It does not call the model-provider `RuntimeService.execute()` path.

- `execution_kind = "media_derivative"`
- `ability_name = "generate_optimized_media_derivative"`
- `ability_family = "vision"`
- `execution_pattern = "whole_run_offload"`
- `task_backend = {"enabled": True}`
- `input_payload` contains `cloud_job_payload` + `source_media_type` + source metadata only
- `storage_mode = "result_only"`
- `retention_ttl = 3600`

Queued media job input is stored in `execution_input_ciphertext` (reusing existing encryption mechanism) so the worker can decrypt it after dequeuing.

For multipart upload source mode, `execution_input_ciphertext` contains the source bytes and minimal media job metadata. For artifact-reference source mode, it contains the source artifact reference and job metadata; the worker loads and verifies the artifact before processing.

## Worker Behavior

### Branch in `_execute_existing_run`

```python
def _execute_existing_run(self, run, *, repository):
    if run.execution_kind == "media_derivative":
        self._execute_media_derivative_run(run, repository=repository)
        return
    # ... existing provider execution chain unchanged
```

### `_execute_media_derivative_run`

1. Decrypt source file binary from `execution_input_ciphertext`
2. Parse `cloud_job_payload` from `input_payload`
3. Call `process_media_derivative()` pure function
4. Persist artifact to `media_derivative_artifacts` table
5. Set `run.result_json` with artifact metadata
6. Mark run succeeded or failed

### Processor — Pure Function

```python
def process_media_derivative(
    *,
    source_bytes: bytes,
    source_media_type: str,
    target_format: str,
    max_width: int,
    quality: int,
) -> MediaDerivativeResult:
```

Processing flow:

1. **Safety limits** — Set bounded image safety limits before decode, including a maximum pixel count. Inputs that exceed the pixel limit fail with `media_derivative.source_too_large`.
2. **Open source** — `Image.open(BytesIO(source_bytes))`, verify the image, reopen it for processing, and extract original dimensions
3. **Normalize source** — Apply EXIF orientation, reject or normalize animated images according to the rules below, and strip metadata from derivative outputs
4. **Format availability check** — If `target_format == "avif"` and Pillow lacks AVIF encoder, raise `MediaDerivativeFormatUnavailableError("avif")` → explicit error `media_derivative.format_unavailable`, no silent degradation
5. **Resize** — If source width > `max_width`, proportional downscale via `Image.thumbnail`; otherwise keep original dimensions
6. **Transcode** — Encode output by `target_format`:
   - `webp`: `save(buf, "WEBP", quality=quality)`
   - `avif`: `save(buf, "AVIF", quality=quality)` (requires libavif-compiled Pillow)
   - `jpeg`: `save(buf, "JPEG", quality=quality)` (flatten alpha to RGB)
   - `png`: `save(buf, "PNG", optimize=True)`
   - `original`: keep original format/encoding, output source bytes directly
7. **Checksum** — `sha256:hex` format
8. **Processing warnings** — e.g. `"source_alpha_flattened_for_jpeg"` when JPEG conversion required alpha flattening
9. **Return `MediaDerivativeResult`** — output_bytes, width, height, filesize, checksum, mime_type, format, warnings

Additional processor rules:

- Animated image input is not supported in the MVP. Multi-frame images return 422 `media_derivative.animated_source_unavailable`.
- `original` preserves source bytes, but still requires successful image decode and source media validation before returning bytes.
- EXIF, ICC, and other metadata are not copied into derivative outputs except when `target_format == "original"`.
- JPEG output always uses RGB and never preserves alpha.
- The processor must close Pillow image handles before returning.

### Success Result Structure (`run.result_json`)

```json
{
  "artifact": {
    "artifact_id": "art_...",
    "artifact_reference": {"artifact_id": "art_..."},
    "download_url": "/v1/runtime/artifacts/art_.../download",
    "expires_at": "...",
    "mime_type": "image/webp",
    "format": "webp",
    "width": 1200,
    "height": 800,
    "filesize_bytes": 123456,
    "checksum": "sha256:...",
    "processing_warnings": []
  }
}
```

No `BLOCKED_RESPONSE_FIELDS` keys are present.

### Failure Paths

| Scenario | error_code | Run status |
|----------|-----------|------------|
| Pillow cannot decode source | `media_derivative.source_decode_failed` | failed |
| Source exceeds image pixel/memory safety limit | `media_derivative.source_too_large` | failed |
| Animated image input | `media_derivative.animated_source_unavailable` | failed |
| AVIF encoding unavailable | `media_derivative.format_unavailable` | failed |
| Pillow processing exception | `media_derivative.processing_failed` | failed |

All failures use `repository.mark_run_failed()`, consistent with existing failure paths.

## Artifact Download

`GET /v1/runtime/artifacts/{artifact_id}/download`

- Auth: `authorize_public_request(required_scope="runtime:read")`
- Query `media_derivative_artifacts` by `artifact_id` and `auth.site_id`
- Not found or site mismatch → 404
- `expires_at <= now` or `purged_at IS NOT NULL` → **410 Gone**, error_code `media_derivative.artifact_expired`
- Return `StreamingResponse`:
  - `Content-Type: {mime_type}`
  - `Content-Disposition: inline; filename="{artifact_id}.{format}"`
  - `X-Content-Type-Options: nosniff`
  - `Cache-Control: private, max-age={remaining_ttl_seconds}`
  - Body: `blob_data` bytes

`filename` uses only the server-generated `artifact_id` and an extension derived from the validated target format. No client-provided filename is reflected.

Artifact download TTL is independent of run result retention. `GET /v1/runs/{run_id}/result` may still return artifact metadata after the artifact expires, but `GET /v1/runtime/artifacts/{artifact_id}/download` must return 410 once the artifact is expired or purged.

## Artifact Cleanup

Reuse existing `ops_cadence` worker mechanism. New function:

```python
def cleanup_expired_artifacts(*, now: datetime | None = None) -> int:
```

- Scan for `expires_at <= now AND purged_at IS NULL`
- Set `purged_at = now`, set `blob_data = b""` (release BYTEA space)
- Return count of purged artifacts
- Called in `ops_cadence` worker alongside `cleanup_expired_run_results`

## Dependencies

Add to `pyproject.toml`:

```toml
"Pillow>=11.0,<12.0",
"python-multipart>=0.0.18,<1.0",
```

AVIF: Not adding `pillow-avif-plugin` to dependencies. If the runtime Pillow is compiled with libavif, AVIF works. If not, the processor detects this and returns `media_derivative.format_unavailable` — no silent degradation.

## New Files

| File | Responsibility |
|------|---------------|
| `app/domain/media_derivatives/__init__.py` | Package init |
| `app/domain/media_derivatives/contracts.py` | Request contract, constants, validation |
| `app/domain/media_derivatives/processor.py` | Pillow processing pure function |
| `app/domain/media_derivatives/artifacts.py` | Artifact CRUD + cleanup |
| `app/api/routes/media_derivatives.py` | Endpoint definitions |
| `migrations/versions/20260602_0034_media_derivative_artifacts.py` | Table migration |
| `tests/api/test_media_derivatives.py` | API integration tests |
| `tests/workers/test_media_derivative_worker.py` | Worker processing tests |

## Modified Files

| File | Change |
|------|--------|
| `app/domain/runtime/service.py` | Add media_derivative branch in `_execute_existing_run` + `_execute_media_derivative_run` method |
| `app/api/auth.py` or `app/core/security.py` | Add media-specific public body limit support without weakening HMAC signing |
| `app/core/models.py` | Add `MediaDerivativeArtifact` ORM model |
| `app/api/main.py` | Register `media_derivatives_router` |
| `pyproject.toml` | Add Pillow + python-multipart |
| `app/workers/ops_cadence.py` | Add `cleanup_expired_artifacts` call |

## Test Coverage

| Test | Verification |
|------|-------------|
| Response contains no WordPress write fields | Iterate `BLOCKED_RESPONSE_FIELDS`, assert no such keys in result_json |
| Endpoint bypasses model routing | Missing media routing profile does not prevent media derivative run creation |
| No provider call record is created | Worker success path leaves `provider_call_records` empty for the run |
| Multipart requires idempotency | Missing `Idempotency-Key` on POST returns `auth.idempotency_required` |
| Multipart raw body is signed | Tampering with source bytes after signing returns `auth.invalid_signature` |
| Media upload uses media-specific body limit | Upload > default runtime 1 MiB but <= 50 MB reaches media validation instead of `auth.payload_too_large` |
| Artifact expires_at is short TTL | Assert `15 <= ttl_minutes <= 60`, actual expires_at within range |
| Expired artifact download returns 410 | Set `expires_at` to past, request download, assert 410 |
| Artifact reference must be same-site | Cross-site artifact reference returns 404 |
| Purged artifact reference is rejected | `purged_at` set, request by `artifact_id`, assert 404 |
| Invalid format (gif) returns 422 | `target_format="gif"`, assert 422 |
| Oversized upload returns 413 | Upload >50MB file, assert 413 |
| Pixel bomb protection | Tiny compressed file with excessive dimensions fails with `media_derivative.source_too_large` |
| Animated image rejected | Multi-frame image returns `media_derivative.animated_source_unavailable` |
| Worker success path | Upload image → queued run → `process_queued_runs()` → verify output format, dimensions, filesize, checksum |
| AVIF unavailable returns explicit error | Mock Pillow without AVIF support, assert `media_derivative.format_unavailable` |
| Video source_media_type returns 422 | `source_media_type="video"`, assert 422 |
