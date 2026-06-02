# Media Derivative Processing Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Cloud-side media derivative processing for images within the existing runtime plane, reusing run_records, Redis queue, and worker infrastructure.

**Architecture:** Add a branch in `_execute_existing_run()` for `execution_kind == "media_derivative"`, with a dedicated `enqueue_media_derivative_run` helper that bypasses model/provider routing. Pillow-based processor as a pure function. BYTEA blob storage for MVP. Short-TTL artifacts with cleanup via ops_cadence.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pillow, python-multipart, Pytest, SQLite (test), Postgres (prod)

**Spec:** `docs/superpowers/specs/2026-06-02-media-derivative-processing-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `app/domain/media_derivatives/__init__.py` | Package init |
| `app/domain/media_derivatives/contracts.py` | Request/response Pydantic models, constants, validation |
| `app/domain/media_derivatives/processor.py` | Pillow processing pure function + result dataclass |
| `app/domain/media_derivatives/artifacts.py` | Artifact repository CRUD + cleanup |
| `app/domain/media_derivatives/errors.py` | Media derivative specific errors |
| `app/api/routes/media_derivatives.py` | POST /v1/runtime/media-derivatives + GET artifacts download |
| `migrations/versions/20260602_0034_media_derivative_artifacts.py` | Alembic migration |
| `tests/api/test_media_derivatives.py` | API integration tests |
| `tests/workers/test_media_derivative_worker.py` | Worker + processor tests |

### Modified Files
| File | Change |
|------|--------|
| `app/core/models.py` | Add `MediaDerivativeArtifact` ORM model |
| `app/domain/runtime/service.py` | Add `enqueue_media_derivative_run` + `_execute_media_derivative_run` + branch in `_execute_existing_run` |
| `app/api/main.py` | Register `media_derivatives_router` |
| `app/api/auth.py` | Add `max_body_bytes` param to `authorize_public_request` |
| `app/core/security.py` | Add `max_body_bytes` param to `authorize_request` / `_validate_payload_size` |
| `app/core/config.py` | Add `artifact_cleanup_interval_seconds` + `media_derivative_max_body_bytes` settings |
| `pyproject.toml` | Add Pillow + python-multipart |
| `app/workers/ops_cadence.py` | Add artifact cleanup cadence task |

---

## Task 1: Add ORM Model + Migration

**Files:**
- Modify: `app/core/models.py`
- Create: `migrations/versions/20260602_0034_media_derivative_artifacts.py`

- [ ] **Step 1: Add `MediaDerivativeArtifact` model to `app/core/models.py`**

Add after the last model class in `app/core/models.py`, before the end of file:

```python
class MediaDerivativeArtifact(Base):
    __tablename__ = "media_derivative_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    storage_ref: Mapped[str] = mapped_column(String(512))
    blob_data: Mapped[bytes] = mapped_column(LargeBinary)
    mime_type: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(16))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    filesize_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(128))
    source_media_type: Mapped[str] = mapped_column(String(16), default="image")
    processing_warnings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
```

Ensure `LargeBinary` is imported from `sqlalchemy` (it is already available as `LargeBinary` or `BLOB`).

- [ ] **Step 2: Create the Alembic migration**

Create `migrations/versions/20260602_0034_media_derivative_artifacts.py`:

```python
"""media_derivative_artifacts

Revision ID: 20260602_0034
Revises: 20260601_0033
Create Date: 2026-06-02

"""

from alembic import op
import sqlalchemy as sa

revision = "20260602_0034"
down_revision = "20260601_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("media_derivative_artifacts"):
        return

    op.create_table(
        "media_derivative_artifacts",
        sa.Column("artifact_id", sa.String(191), nullable=False),
        sa.Column("run_id", sa.String(191), nullable=False),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("blob_data", sa.LargeBinary, nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filesize_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("source_media_type", sa.String(16), nullable=False, server_default="image"),
        sa.Column("processing_warnings_json", sa.JSON, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["run_records.run_id"]),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    for index_name, columns in (
        ("ix_mda_run_id", ["run_id"]),
        ("ix_mda_site_id", ["site_id"]),
    ):
        op.create_index(index_name, "media_derivative_artifacts", columns)
    op.create_index(
        "ix_mda_expires_at",
        "media_derivative_artifacts",
        ["expires_at"],
        postgresql_where=sa.text("purged_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("media_derivative_artifacts"):
        op.drop_table("media_derivative_artifacts")
```

- [ ] **Step 3: Verify model imports cleanly**

Run: `python -c "from app.core.models import MediaDerivativeArtifact; print(MediaDerivativeArtifact.__tablename__)"`
Expected: `media_derivative_artifacts`

- [ ] **Step 4: Commit**

```bash
git add app/core/models.py migrations/versions/20260602_0034_media_derivative_artifacts.py
git commit -m "feat: add MediaDerivativeArtifact ORM model and migration"
```

---

## Task 2: Add Pyproject Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add Pillow and python-multipart to dependencies**

In `pyproject.toml`, add to the `dependencies` list (after the `opentelemetry-exporter-otlp` line):

```toml
  "Pillow>=11.0,<12.0",
  "python-multipart>=0.0.18,<1.0",
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -e ".[dev]"` or `uv sync`
Expected: Pillow and python-multipart installed successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add Pillow and python-multipart dependencies"
```

---

## Task 3: Contracts + Errors Module

**Files:**
- Create: `app/domain/media_derivatives/__init__.py`
- Create: `app/domain/media_derivatives/contracts.py`
- Create: `app/domain/media_derivatives/errors.py`

- [ ] **Step 1: Create `app/domain/media_derivatives/__init__.py`**

Empty file.

- [ ] **Step 2: Create `app/domain/media_derivatives/errors.py`**

```python
from __future__ import annotations


class MediaDerivativeErrorBase(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class MediaDerivativeInvalidSourceError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(400, "media_derivative.invalid_source", "exactly one source mode is required")


class MediaDerivativeFormatUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_derivative.format_unavailable",
            f"format '{fmt}' is not available in this runtime environment",
        )


class MediaDerivativeInvalidFormatError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_derivative.invalid_format",
            f"target_format '{fmt}' is not supported",
        )


class MediaDerivativeSourceMediaTypeUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, media_type: str) -> None:
        super().__init__(
            422,
            "media_derivative.source_media_type_unavailable",
            f"source_media_type '{media_type}' is not supported",
        )


class MediaDerivativeUploadTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(413, "media_derivative.upload_too_large", "uploaded file exceeds the size limit")


class MediaDerivativeSourceDecodeFailedError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(422, "media_derivative.source_decode_failed", "source image could not be decoded")


class MediaDerivativeSourceTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(422, "media_derivative.source_too_large", "source image exceeds pixel count safety limit")


class MediaDerivativeAnimatedSourceUnavailableError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            422,
            "media_derivative.animated_source_unavailable",
            "animated image input is not supported",
        )


class MediaDerivativeProcessingFailedError(MediaDerivativeErrorBase):
    def __init__(self, detail: str = "") -> None:
        message = f"media derivative processing failed: {detail}" if detail else "media derivative processing failed"
        super().__init__(422, "media_derivative.processing_failed", message)


class MediaDerivativeSourceArtifactNotFoundError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(404, "media_derivative.source_artifact_not_found", "referenced source artifact not found")


class MediaDerivativeArtifactExpiredError(MediaDerivativeErrorBase):
    def __init__(self, artifact_id: str) -> None:
        super().__init__(
            410,
            "media_derivative.artifact_expired",
            f"artifact '{artifact_id}' has expired and is no longer available",
        )
```

- [ ] **Step 3: Create `app/domain/media_derivatives/contracts.py`**

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_TARGET_FORMATS = frozenset({"webp", "avif", "jpeg", "png", "original"})
ALLOWED_SOURCE_MEDIA_TYPES = frozenset({"image"})
MAX_UPLOAD_BYTES_IMAGE = 50 * 1024 * 1024
MAX_PIXEL_COUNT = 178_956_970
ARTIFACT_DEFAULT_TTL_MINUTES = 30
ARTIFACT_MIN_TTL_MINUTES = 15
ARTIFACT_MAX_TTL_MINUTES = 60

BLOCKED_RESPONSE_FIELDS = frozenset({
    "wordpress_write_policy",
    "wordpress_write_target",
    "attachment_metadata",
    "metadata_patch",
    "replace_file",
    "apply_decision",
    "approval_decision",
    "target_attachment_id",
})

MIME_TYPE_BY_FORMAT: dict[str, str] = {
    "webp": "image/webp",
    "avif": "image/avif",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

PILLOW_FORMAT_BY_TARGET: dict[str, str] = {
    "webp": "WEBP",
    "avif": "AVIF",
    "jpeg": "JPEG",
    "png": "PNG",
}


class CloudJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["generate_optimized_media_derivative"]
    target_format: str
    max_width: int = 1200
    quality: int = 82
    source_media_type: str = "image"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str


class MediaDerivativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_contract_version: Literal["media_derivative_cloud_request.v1"]
    cloud_job_payload: CloudJobPayload
    source: SourceRef | None = None
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES

    @model_validator(mode="after")
    def validate_fields(self) -> MediaDerivativeRequest:
        payload = self.cloud_job_payload
        if payload.target_format not in ALLOWED_TARGET_FORMATS:
            raise ValueError(f"target_format '{payload.target_format}' is not supported")
        if payload.source_media_type not in ALLOWED_SOURCE_MEDIA_TYPES:
            raise ValueError(f"source_media_type '{payload.source_media_type}' is not supported")
        if not (1 <= payload.quality <= 100):
            raise ValueError("quality must be between 1 and 100")
        if not (1 <= payload.max_width <= 10000):
            raise ValueError("max_width must be between 1 and 10000")
        if not (ARTIFACT_MIN_TTL_MINUTES <= self.ttl_minutes <= ARTIFACT_MAX_TTL_MINUTES):
            raise ValueError(f"ttl_minutes must be between {ARTIFACT_MIN_TTL_MINUTES} and {ARTIFACT_MAX_TTL_MINUTES}")
        return self


def validate_blocked_fields(data: dict[str, Any]) -> None:
    for key in BLOCKED_RESPONSE_FIELDS:
        if key in data:
            raise ValueError(f"response contains blocked field '{key}'")
```

- [ ] **Step 4: Verify imports cleanly**

Run: `python -c "from app.domain.media_derivatives.contracts import MediaDerivativeRequest; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/domain/media_derivatives/
git commit -m "feat: add media_derivatives contracts and errors modules"
```

---

## Task 4: Processor Module

**Files:**
- Create: `app/domain/media_derivatives/processor.py`

- [ ] **Step 1: Create `app/domain/media_derivatives/processor.py`**

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image

from app.domain.media_derivatives.contracts import (
    MAX_PIXEL_COUNT,
    MIME_TYPE_BY_FORMAT,
    PILLOW_FORMAT_BY_TARGET,
    ALLOWED_TARGET_FORMATS,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeProcessingFailedError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
)


@dataclass(slots=True)
class MediaDerivativeResult:
    output_bytes: bytes
    width: int
    height: int
    filesize_bytes: int
    checksum: str
    mime_type: str
    format: str
    processing_warnings: list[str] = field(default_factory=list)


def _check_format_available(target_format: str) -> None:
    pillow_format = PILLOW_FORMAT_BY_TARGET.get(target_format)
    if pillow_format is None:
        return
    try:
        Image.init()
        if pillow_format not in Image.SAVE:
            raise MediaDerivativeFormatUnavailableError(target_format)
    except MediaDerivativeFormatUnavailableError:
        raise
    except Exception:
        raise MediaDerivativeFormatUnavailableError(target_format)


def process_media_derivative(
    *,
    source_bytes: bytes,
    source_media_type: str,
    target_format: str,
    max_width: int,
    quality: int,
) -> MediaDerivativeResult:
    if target_format != "original":
        _check_format_available(target_format)

    img: Image.Image | None = None
    try:
        try:
            img = Image.open(BytesIO(source_bytes))
            img.verify()
        except Exception:
            raise MediaDerivativeSourceDecodeFailedError()

        img = Image.open(BytesIO(source_bytes))
        img.load()

        if hasattr(img, "n_frames") and getattr(img, "n_frames", 1) > 1:
            raise MediaDerivativeAnimatedSourceUnavailableError()

        if img.width * img.height > MAX_PIXEL_COUNT:
            raise MediaDerivativeSourceTooLargeError()

        try:
            from PIL import ExifTags
            img_exif = img.getexif()
            if img_exif:
                orientation = img_exif.get(ExifTags.Base.Orientation, None)
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        warnings: list[str] = []

        if target_format == "original":
            output_bytes = source_bytes
            result_width = img.width
            result_height = img.height
            fmt = img.format or "PNG"
            mime_type = img.get_format_mimetype() if hasattr(img, "get_format_mimetype") else MIME_TYPE_BY_FORMAT.get(fmt.lower(), "image/png")
        else:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.LANCZOS)

            pillow_format = PILLOW_FORMAT_BY_TARGET[target_format]
            mime_type = MIME_TYPE_BY_FORMAT[target_format]

            save_kwargs: dict[str, Any] = {}
            if target_format == "jpeg":
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                    warnings.append("source_alpha_flattened_for_jpeg")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            elif target_format == "webp":
                save_kwargs["quality"] = quality
            elif target_format == "avif":
                save_kwargs["quality"] = quality
            elif target_format == "png":
                save_kwargs["optimize"] = True
                if img.mode == "RGBA":
                    pass
                elif img.mode != "RGB":
                    img = img.convert("RGB")

            buf = BytesIO()
            img.save(buf, format=pillow_format, **save_kwargs)
            output_bytes = buf.getvalue()

            result_width = img.width
            result_height = img.height
            fmt = target_format

        checksum = hashlib.sha256(output_bytes).hexdigest()
        return MediaDerivativeResult(
            output_bytes=output_bytes,
            width=result_width,
            height=result_height,
            filesize_bytes=len(output_bytes),
            checksum=f"sha256:{checksum}",
            mime_type=mime_type,
            format=fmt,
            processing_warnings=warnings,
        )
    except (
        MediaDerivativeSourceDecodeFailedError,
        MediaDerivativeFormatUnavailableError,
        MediaDerivativeSourceTooLargeError,
        MediaDerivativeAnimatedSourceUnavailableError,
    ):
        raise
    except Exception as exc:
        raise MediaDerivativeProcessingFailedError(str(exc)) from exc
    finally:
        if img is not None:
            img.close()
```

- [ ] **Step 2: Verify imports cleanly**

Run: `python -c "from app.domain.media_derivatives.processor import process_media_derivative; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/domain/media_derivatives/processor.py
git commit -m "feat: add media derivative processor with Pillow"
```

---

## Task 5: Artifacts Module

**Files:**
- Create: `app/domain/media_derivatives/artifacts.py`

- [ ] **Step 1: Create `app/domain/media_derivatives/artifacts.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.models import MediaDerivativeArtifact
from app.domain.media_derivatives.contracts import ARTIFACT_DEFAULT_TTL_MINUTES
from app.domain.media_derivatives.processor import MediaDerivativeResult


def create_artifact(
    *,
    session: Session,
    run_id: str,
    site_id: str,
    result: MediaDerivativeResult,
    source_media_type: str,
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES,
) -> MediaDerivativeArtifact:
    artifact_id = f"art_{uuid4().hex}"
    now = datetime.now(UTC)
    artifact = MediaDerivativeArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        site_id=site_id,
        storage_ref=f"blob://media_derivative/{artifact_id}",
        blob_data=result.output_bytes,
        mime_type=result.mime_type,
        format=result.format,
        width=result.width,
        height=result.height,
        filesize_bytes=result.filesize_bytes,
        checksum=result.checksum,
        source_media_type=source_media_type,
        processing_warnings_json={"warnings": result.processing_warnings},
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    session.add(artifact)
    session.flush()
    return artifact


def get_artifact(
    session: Session,
    artifact_id: str,
    *,
    site_id: str | None = None,
) -> MediaDerivativeArtifact | None:
    statement = select(MediaDerivativeArtifact).where(
        MediaDerivativeArtifact.artifact_id == artifact_id,
    )
    if site_id:
        statement = statement.where(MediaDerivativeArtifact.site_id == site_id)
    return session.scalar(statement)


def is_artifact_expired(artifact: MediaDerivativeArtifact, *, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    if artifact.purged_at is not None:
        return True
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= current_time


def cleanup_expired_artifacts(
    *,
    database_url: str,
    now: datetime | None = None,
    session: Session | None = None,
    batch_size: int = 100,
) -> int:
    from app.core.db import get_session as _get_session

    current_time = now or datetime.now(UTC)
    purged_total = 0

    def _cleanup_with_session(s: Session) -> int:
        statement = (
            select(MediaDerivativeArtifact)
            .where(
                MediaDerivativeArtifact.expires_at <= current_time,
                MediaDerivativeArtifact.purged_at.is_(None),
            )
            .limit(batch_size)
        )
        artifacts = list(s.scalars(statement))
        for artifact in artifacts:
            artifact.purged_at = current_time
            artifact.blob_data = b""
        s.flush()
        return len(artifacts)

    if session is not None:
        return _cleanup_with_session(session)

    with _get_session(database_url) as s:
        count = _cleanup_with_session(s)
        s.commit()
        return count


def build_artifact_result_json(artifact: MediaDerivativeArtifact) -> dict[str, object]:
    warnings: list[str] = []
    if isinstance(artifact.processing_warnings_json, dict):
        warnings = artifact.processing_warnings_json.get("warnings", [])
    elif isinstance(artifact.processing_warnings_json, list):
        warnings = artifact.processing_warnings_json
    return {
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "artifact_reference": {"artifact_id": artifact.artifact_id},
            "download_url": f"/v1/runtime/artifacts/{artifact.artifact_id}/download",
            "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
            "mime_type": artifact.mime_type,
            "format": artifact.format,
            "width": artifact.width,
            "height": artifact.height,
            "filesize_bytes": artifact.filesize_bytes,
            "checksum": artifact.checksum,
            "processing_warnings": warnings,
        },
    }
```

- [ ] **Step 2: Verify imports cleanly**

Run: `python -c "from app.domain.media_derivatives.artifacts import create_artifact; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/domain/media_derivatives/artifacts.py
git commit -m "feat: add media derivative artifact repository"
```

---

## Task 6: Auth — Media-Specific Body Limit

**Files:**
- Modify: `app/core/security.py` (add `max_body_bytes` parameter)
- Modify: `app/api/auth.py` (pass `max_body_bytes` through)
- Modify: `app/core/config.py` (add settings)

- [ ] **Step 1: Modify `_validate_payload_size` in `app/core/security.py`**

Find the `_validate_payload_size` function (around line 233). It currently uses the hardcoded `PUBLIC_RUNTIME_MAX_BODY_BYTES`. Add a `max_body_bytes` parameter:

Change:
```python
def _validate_payload_size(body: bytes) -> None:
    if len(body) > PUBLIC_RUNTIME_MAX_BODY_BYTES:
```

To:
```python
def _validate_payload_size(body: bytes, *, max_body_bytes: int = PUBLIC_RUNTIME_MAX_BODY_BYTES) -> None:
    if len(body) > max_body_bytes:
```

- [ ] **Step 2: Propagate `max_body_bytes` through `authorize_request` in `app/core/security.py`**

Find the `authorize_request` function. It calls `_validate_payload_size(body)`. Add `max_body_bytes` parameter to `authorize_request` signature and pass it through.

In the function signature, add `max_body_bytes: int = PUBLIC_RUNTIME_MAX_BODY_BYTES,`.

Change the call from `_validate_payload_size(body)` to `_validate_payload_size(body, max_body_bytes=max_body_bytes)`.

- [ ] **Step 3: Modify `authorize_public_request` in `app/api/auth.py`**

Add `max_body_bytes: int | None = None,` parameter to `authorize_public_request`.

Pass it through to `authorize_request()` call: `max_body_bytes=max_body_bytes or PUBLIC_RUNTIME_MAX_BODY_BYTES`.

Add import: `from app.core.security import PUBLIC_RUNTIME_MAX_BODY_BYTES`

- [ ] **Step 4: Add settings to `app/core/config.py`**

In the `Settings` class, add:

```python
media_derivative_max_body_bytes: int = Field(default=52428800, description="Max body bytes for media derivative uploads (50MB + 1MB framing)")
artifact_cleanup_interval_seconds: int = Field(default=3600, description="Interval for expired artifact cleanup")
```

Add validation: `artifact_cleanup_interval_seconds >= 60` (similar to existing interval validations).

- [ ] **Step 5: Verify existing tests still pass**

Run: `python -m pytest tests/api/test_runtime_execute.py -x -q --timeout=30 2>&1 | head -20`
Expected: Tests still pass (we only added optional parameters with defaults).

- [ ] **Step 6: Commit**

```bash
git add app/core/security.py app/api/auth.py app/core/config.py
git commit -m "feat: add media-specific body limit support for auth"
```

---

## Task 7: Runtime Service — `enqueue_media_derivative_run` + Worker Branch

**Files:**
- Modify: `app/domain/runtime/service.py`

- [ ] **Step 1: Add `enqueue_media_derivative_run` method to `RuntimeService`**

Add this method to the `RuntimeService` class in `app/domain/runtime/service.py`. Place it after the existing `execute` method (around line 319), before `process_next_queued_run`:

```python
    def enqueue_media_derivative_run(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        source_bytes: bytes,
        ttl_minutes: int = 30,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        resolved_trace_id = trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        resolved_idempotency_key = idempotency_key or f"auto_{uuid4().hex}"

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, site_id)

            existing = repository.get_run_by_idempotency(site_id, resolved_idempotency_key)
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=site_id,
                ability_family="vision",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                data_classification="internal",
                trace_id=resolved_trace_id,
                idempotency_key=resolved_idempotency_key,
                request_kind="execute",
                run_id=run_id,
            )

            execution_input_ciphertext = encrypt_runtime_execution_input(
                input_payload,
                settings=self.settings,
            )

            encrypted_source = encrypt_runtime_execution_input(
                {"_source_bytes_b64": self._encode_source_bytes(source_bytes)},
                settings=self.settings,
            )

            media_input = {
                **input_payload,
                "_encrypted_source_ref": encrypted_source,
            }

            policy = {
                "storage_mode": "result_only",
                "execution_contract": {
                    "ability_name": "generate_optimized_media_derivative",
                    "contract_version": "media_derivative_cloud_request.v1",
                    "profile_id": "media_derivative.worker",
                    "execution_pattern": "whole_run_offload",
                    "data_classification": "internal",
                    "storage_mode": "result_only",
                    "timeout_seconds": 300,
                    "retry_max": 0,
                    "retention_ttl": 3600,
                    "task_backend": {"enabled": True},
                },
            }

            run = repository.create_run(
                run_id=run_id,
                site_id=site_id,
                account_id=str(commercial_decision.get("account_id") or "") or None,
                subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                ability_name="generate_optimized_media_derivative",
                ability_family="vision",
                skill_id="",
                workflow_id="",
                contract_version="media_derivative_cloud_request.v1",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                execution_pattern="whole_run_offload",
                data_classification="internal",
                profile_id="media_derivative.worker",
                canonical_run_id=None,
                status="queued",
                idempotency_key=resolved_idempotency_key,
                request_fingerprint=self._build_request_fingerprint_for_media_derivative(
                    site_id, input_payload,
                ),
                trace_id=resolved_trace_id,
                input_json={},
                execution_input_ciphertext=encrypt_runtime_execution_input(
                    media_input,
                    settings=self.settings,
                ),
                policy_json=policy,
                selected_provider_id="media_derivative",
                selected_model_id="pillow",
                selected_instance_id="cloud-worker",
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._publish_queue_signal(run.run_id)
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    @staticmethod
    def _encode_source_bytes(data: bytes) -> str:
        import base64
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def _decode_source_bytes(encoded: str) -> bytes:
        import base64
        return base64.b64decode(encoded)

    def _build_request_fingerprint_for_media_derivative(
        self,
        site_id: str,
        input_payload: dict[str, Any],
    ) -> str:
        canonical_payload = json.dumps(
            {
                "site_id": site_id,
                "execution_kind": "media_derivative",
                "input": input_payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 2: Add `_execute_media_derivative_run` method to `RuntimeService`**

Add this method to `RuntimeService`, after `enqueue_media_derivative_run`:

```python
    def _execute_media_derivative_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        from app.domain.media_derivatives.artifacts import create_artifact, build_artifact_result_json
        from app.domain.media_derivatives.contracts import (
            ARTIFACT_DEFAULT_TTL_MINUTES,
        )
        from app.domain.media_derivatives.errors import (
            MediaDerivativeFormatUnavailableError,
            MediaDerivativeSourceDecodeFailedError,
            MediaDerivativeSourceTooLargeError,
            MediaDerivativeAnimatedSourceUnavailableError,
            MediaDerivativeProcessingFailedError,
        )
        from app.domain.media_derivatives.processor import process_media_derivative

        media_input = self._get_execution_input_payload(run)
        cloud_job_payload = media_input.get("cloud_job_payload", {})
        source_media_type = cloud_job_payload.get("source_media_type", "image")
        target_format = cloud_job_payload.get("target_format", "webp")
        max_width = int(cloud_job_payload.get("max_width", 1200))
        quality = int(cloud_job_payload.get("quality", 82))
        ttl_minutes = int(media_input.get("ttl_minutes", ARTIFACT_DEFAULT_TTL_MINUTES))

        encrypted_source_ref = media_input.get("_encrypted_source_ref")
        source_bytes = b""
        if encrypted_source_ref and isinstance(encrypted_source_ref, str):
            decrypted = decrypt_runtime_execution_input(
                encrypted_source_ref,
                settings=self.settings,
            )
            source_b64 = decrypted.get("_source_bytes_b64", "")
            if source_b64:
                source_bytes = self._decode_source_bytes(source_b64)

        if not source_bytes:
            repository.mark_run_failed(
                run,
                error_code="media_derivative.source_decode_failed",
                error_message="no source bytes found in media derivative run",
            )
            return

        try:
            result = process_media_derivative(
                source_bytes=source_bytes,
                source_media_type=source_media_type,
                target_format=target_format,
                max_width=max_width,
                quality=quality,
            )
        except (
            MediaDerivativeSourceDecodeFailedError,
            MediaDerivativeSourceTooLargeError,
            MediaDerivativeAnimatedSourceUnavailableError,
            MediaDerivativeFormatUnavailableError,
            MediaDerivativeProcessingFailedError,
        ) as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
            )
            return

        artifact = create_artifact(
            session=repository.session,
            run_id=run.run_id,
            site_id=run.site_id,
            result=result,
            source_media_type=source_media_type,
            ttl_minutes=ttl_minutes,
        )
        result_json = build_artifact_result_json(artifact)
        repository.mark_run_succeeded(
            run,
            result_json=result_json,
            provider_id="media_derivative",
            model_id="pillow",
            instance_id="cloud-worker",
            fallback_used=False,
        )
```

- [ ] **Step 3: Add the branch in `_execute_existing_run`**

Find the `_execute_existing_run` method (around line 1511). Add the branch at the very beginning:

Change:
```python
    def _execute_existing_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
```

To:
```python
    def _execute_existing_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        if run.execution_kind == "media_derivative":
            self._execute_media_derivative_run(run, repository=repository)
            return

        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `python -c "from app.domain.runtime.service import RuntimeService; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/domain/runtime/service.py
git commit -m "feat: add enqueue_media_derivative_run and worker branch"
```

---

## Task 8: API Routes

**Files:**
- Create: `app/api/routes/media_derivatives.py`
- Modify: `app/api/main.py`

- [ ] **Step 1: Create `app/api/routes/media_derivatives.py`**

```python
from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.config import Settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.core.models import MediaDerivativeArtifact
from app.core.security import RequestAuthContext
from app.domain.media_derivatives.artifacts import (
    get_artifact,
    is_artifact_expired,
    cleanup_expired_artifacts,
)
from app.domain.media_derivatives.contracts import (
    ALLOWED_TARGET_FORMATS,
    ALLOWED_SOURCE_MEDIA_TYPES,
    BLOCKED_RESPONSE_FIELDS,
    MAX_UPLOAD_BYTES_IMAGE,
    MediaDerivativeRequest,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeErrorBase,
    MediaDerivativeArtifactExpiredError,
)
from app.domain.runtime.service import RuntimeService

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/runtime", tags=["media-derivatives"])


def _get_runtime_service(request: Request) -> RuntimeService:
    services = get_cloud_services(request)
    return RuntimeService(
        services.settings.database_url,
        settings=services.settings,
        providers=resolve_execution_provider_adapters(
            services.settings,
            base_providers=services.providers,
        ),
        runtime_queue=services.runtime_queue,
        callback_dispatcher=services.callback_dispatcher,
        callback_max_attempts=services.settings.runtime_callback_max_attempts,
        callback_retry_backoff_seconds=services.settings.runtime_callback_retry_backoff_seconds,
    )


def _media_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    trace_id: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data={},
            trace_id=trace_id,
            revision="md1",
        ),
    )


def _parse_request_json(request_str: str) -> MediaDerivativeRequest:
    data = json.loads(request_str)
    return MediaDerivativeRequest.model_validate(data)


@router.post("/media-derivatives")
async def create_media_derivative(
    request: Request,
    request_form: str = Form(..., alias="request"),
    source_file: UploadFile | None = File(None),
) -> Any:
    services = get_cloud_services(request)
    max_body = services.settings.media_derivative_max_body_bytes
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
        max_body_bytes=max_body,
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        derivative_request = _parse_request_json(request_form)
    except json.JSONDecodeError:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_request",
            message="request JSON is invalid",
            trace_id=auth.trace_id,
        )
    except ValueError as exc:
        error_message = str(exc)
        status_code = 422
        error_code = "media_derivative.validation_error"

        if "target_format" in error_message:
            error_code = "media_derivative.invalid_format"
        elif "source_media_type" in error_message:
            error_code = "media_derivative.source_media_type_unavailable"
        elif "ttl_minutes" in error_message:
            error_code = "media_derivative.validation_error"
        elif "quality" in error_message or "max_width" in error_message:
            error_code = "media_derivative.validation_error"

        return _media_error_response(
            status_code=status_code,
            error_code=error_code,
            message=error_message,
            trace_id=auth.trace_id,
        )

    source_bytes: bytes | None = None
    source_artifact_id: str | None = None

    if source_file is not None:
        source_bytes = await source_file.read()
        if len(source_bytes) > MAX_UPLOAD_BYTES_IMAGE:
            return _media_error_response(
                status_code=413,
                error_code="media_derivative.upload_too_large",
                message="uploaded file exceeds the size limit",
                trace_id=auth.trace_id,
            )
    elif derivative_request.source is not None and derivative_request.source.artifact_id:
        source_artifact_id = derivative_request.source.artifact_id
    else:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_source",
            message="exactly one source mode is required",
            trace_id=auth.trace_id,
        )

    if source_artifact_id:
        with get_session(services.settings.database_url) as session:
            artifact = get_artifact(
                session,
                source_artifact_id,
                site_id=auth.site_id,
            )
            if artifact is None or is_artifact_expired(artifact):
                return _media_error_response(
                    status_code=404,
                    error_code="media_derivative.source_artifact_not_found",
                    message="referenced source artifact not found",
                    trace_id=auth.trace_id,
                )
            source_bytes = artifact.blob_data
            session.commit()

    if not source_bytes:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_source",
            message="no source data available",
            trace_id=auth.trace_id,
        )

    input_payload = {
        "cloud_job_payload": derivative_request.cloud_job_payload.model_dump(),
        "source_media_type": derivative_request.cloud_job_payload.source_media_type,
        "ttl_minutes": derivative_request.ttl_minutes,
    }

    service = _get_runtime_service(request)

    try:
        result = await run_in_threadpool(
            service.enqueue_media_derivative_run,
            site_id=auth.site_id,
            input_payload=input_payload,
            source_bytes=source_bytes,
            ttl_minutes=derivative_request.ttl_minutes,
            idempotency_key=auth.idempotency_key,
            trace_id=auth.trace_id,
        )
    except MediaDerivativeErrorBase as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
        )

    success_statuses = {"queued", "running", "succeeded"}
    status = "ok" if result.status in success_statuses else "error"
    error_code = "" if result.status in success_statuses else result.error_code
    return JSONResponse(
        content=build_envelope(
            status=status,
            error_code=error_code,
            message="media derivative queued" if result.status == "queued" else "media derivative processed",
            data={
                "run_id": result.run_id,
                "status": result.status,
                "trace_id": result.trace_id,
                "execution_context": {
                    "skill_id": result.execution_context.skill_id,
                    "ability_family": result.execution_context.ability_family,
                    "execution_pattern": result.execution_context.execution_pattern,
                },
                "result": result.result,
            },
            trace_id=result.trace_id,
            revision="md1",
        ),
    )


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    request: Request,
    artifact_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    services = get_cloud_services(request)
    with get_session(services.settings.database_url) as session:
        artifact = get_artifact(session, artifact_id, site_id=auth.site_id)
        if artifact is None:
            return _media_error_response(
                status_code=404,
                error_code="media_derivative.artifact_not_found",
                message="artifact not found",
                trace_id=auth.trace_id,
            )

        if is_artifact_expired(artifact):
            return _media_error_response(
                status_code=410,
                error_code="media_derivative.artifact_expired",
                message=f"artifact '{artifact_id}' has expired",
                trace_id=auth.trace_id,
            )

        from datetime import UTC, datetime

        remaining_seconds = 0
        if artifact.expires_at:
            expires_at = artifact.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            remaining = expires_at - datetime.now(UTC)
            remaining_seconds = max(0, int(remaining.total_seconds()))

        blob_data = artifact.blob_data or b""
        session.commit()

    format_ext = artifact.format
    if format_ext == "jpeg":
        format_ext = "jpg"

    return StreamingResponse(
        iter([blob_data]),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{artifact.artifact_id}.{format_ext}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": f"private, max-age={remaining_seconds}",
        },
    )
```

- [ ] **Step 2: Register router in `app/api/main.py`**

Add import at the top of `app/api/main.py`:

```python
from app.api.routes.media_derivatives import router as media_derivatives_router
```

Add `app.include_router(media_derivatives_router)` after the existing `app.include_router(runtime_router)` line (around line 153).

- [ ] **Step 3: Verify the app starts**

Run: `python -c "from app.api.main import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/api/routes/media_derivatives.py app/api/main.py
git commit -m "feat: add media derivative API routes"
```

---

## Task 9: Ops Cadence — Artifact Cleanup

**Files:**
- Modify: `app/workers/ops_cadence.py`

- [ ] **Step 1: Add artifact cleanup cadence task**

In `app/workers/ops_cadence.py`, add a runner function after the existing `_run_provider_health_scan`:

```python
def _run_artifact_cleanup(settings: Settings) -> dict[str, object]:
    from app.domain.media_derivatives.artifacts import cleanup_expired_artifacts

    purged = cleanup_expired_artifacts(database_url=settings.database_url)
    return {"purged_artifacts": purged}
```

Then in the `cadence_task_specs()` function, add a new entry to the returned list:

```python
    CadenceTaskSpec(
        task_id="artifact_cleanup",
        event_kind="runtime.artifact_cleanup.cadence",
        interval_seconds=lambda s: s.artifact_cleanup_interval_seconds,
        runner=_run_artifact_cleanup,
    ),
```

- [ ] **Step 2: Verify module imports cleanly**

Run: `python -c "from app.workers.ops_cadence import cadence_task_specs; print(len(cadence_task_specs(Settings()))); print('OK')"`
Expected: A number one higher than before (7 instead of 6), and `OK`.

- [ ] **Step 3: Commit**

```bash
git add app/workers/ops_cadence.py
git commit -m "feat: add artifact cleanup to ops cadence worker"
```

---

## Task 10: API Integration Tests

**Files:**
- Create: `tests/api/test_media_derivatives.py`

- [ ] **Step 1: Create `tests/api/test_media_derivatives.py`**

```python
from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaDerivativeArtifact
from app.core.services import CloudServices
from app.domain.media_derivatives.contracts import BLOCKED_RESPONSE_FIELDS
from app.domain.runtime.service import RuntimeService
from tests.conftest import build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'media-derivative-api.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    runtime_queue: InMemoryRuntimeQueue | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    return database_url, TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={},
                runtime_queue=runtime_queue or InMemoryRuntimeQueue(),
            )
        )
    )


def _make_png_bytes(width: int = 100, height: int = 80) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def _build_multipart_body(
    request_dict: dict,
    image_bytes: bytes,
    boundary: str = "boundary123",
) -> tuple[bytes, str]:
    parts = []
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="request"')
    parts.append(b"")
    parts.append(json.dumps(request_dict).encode())
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="source_file"; filename="test.png"')
    parts.append(b"Content-Type: image/png")
    parts.append(b"")
    parts.append(image_bytes)
    parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def _process_queued_runs(database_url: str) -> None:
    service = RuntimeService(
        database_url,
        settings=Settings(
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
        ),
    )
    service.process_queued_runs(max_runs=10, timeout_seconds=0)


def test_worker_success_path(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(200, 160)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
            "ttl_minutes": 30,
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-worker-test-001",
            nonce="nonce-worker-test-001",
        )
        headers["content-type"] = content_type

        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["status"] == "queued"
        run_id = data["run_id"]

        _process_queued_runs(database_url)

        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_headers["content-type"] = "application/json"
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200, result_response.json()
        result_data = result_response.json()["data"]
        assert result_data["status"] == "succeeded"
        artifact = result_data["result"]["artifact"]
        assert artifact["format"] == "webp"
        assert artifact["width"] == 100
        assert artifact["height"] == 80
        assert artifact["filesize_bytes"] > 0
        assert artifact["checksum"].startswith("sha256:")
        assert artifact["mime_type"] == "image/webp"
        assert artifact["processing_warnings"] == []
    finally:
        dispose_engine(database_url)


def test_response_contains_no_wordpress_write_fields(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-no-wp-001",
            nonce="nonce-no-wp-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        response_text = json.dumps(response.json())
        for field in BLOCKED_RESPONSE_FIELDS:
            assert field not in response_text, f"blocked field '{field}' found in response"
    finally:
        dispose_engine(database_url)


def test_invalid_format_gif_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "gif",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body = json.dumps(request_dict).encode()
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-gif-001",
            nonce="nonce-gif-001",
        )
        headers["content-type"] = "application/json"
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert "invalid_format" in response.json()["error_code"]
    finally:
        dispose_engine(database_url)


def test_video_source_media_type_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "video",
            },
        }
        body = json.dumps(request_dict).encode()
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-video-001",
            nonce="nonce-video-001",
        )
        headers["content-type"] = "application/json"
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert "source_media_type_unavailable" in response.json()["error_code"]
    finally:
        dispose_engine(database_url)


def test_expired_artifact_download_returns_410(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-expire-001",
            nonce="nonce-expire-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            session.commit()
            artifact_id = artifact.artifact_id

        dl_headers = build_auth_headers(
            "GET",
            f"/v1/runtime/artifacts/{artifact_id}/download",
            site_id="site_alpha",
        )
        dl_response = client.get(f"/v1/runtime/artifacts/{artifact_id}/download", headers=dl_headers)
        assert dl_response.status_code == 410
    finally:
        dispose_engine(database_url)


def test_artifact_reference_must_be_same_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-cross-site-001",
            nonce="nonce-cross-site-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact_id = artifact.artifact_id

        ref_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
            "source": {"artifact_id": artifact_id},
        }
        ref_body = json.dumps(ref_request).encode()
        ref_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_beta",
            key_id="key_beta",
            body=ref_body,
            idempotency_key="idem-cross-site-002",
            nonce="nonce-cross-site-002",
        )
        ref_headers["content-type"] = "application/json"
        ref_response = client.post("/v1/runtime/media-derivatives", content=ref_body, headers=ref_headers)
        assert ref_response.status_code == 404
    finally:
        dispose_engine(database_url)


def test_animated_image_rejected(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_animated_gif_bytes()
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-animated-001",
            nonce="nonce-animated-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        run_id = response.json()["data"]["run_id"]
        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_headers["content-type"] = "application/json"
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200
        result_data = result_response.json()["data"]
        assert result_data["status"] == "failed"
        assert "animated_source_unavailable" in (result_data.get("error_code") or "")
    finally:
        dispose_engine(database_url)


def test_no_provider_call_record_created(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-no-provider-001",
            nonce="nonce-no-provider-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        from app.core.models import ProviderCallRecord
        with get_session(database_url) as session:
            count = len(list(session.query(ProviderCallRecord).all()))
            assert count == 0, "no provider_call_records should be created for media derivative runs"
    finally:
        dispose_engine(database_url)


def test_artifact_expires_at_is_short_ttl(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
            "ttl_minutes": 20,
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-ttl-001",
            nonce="nonce-ttl-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            created_at = artifact.created_at
            expires_at = artifact.expires_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            delta_minutes = (expires_at - created_at).total_seconds() / 60
            assert 15 <= delta_minutes <= 60, f"TTL {delta_minutes} min is outside 15-60 range"
    finally:
        dispose_engine(database_url)
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/api/test_media_derivatives.py -x -v --timeout=60`
Expected: Most tests pass. Some may fail due to multipart auth handling — iterate on the multipart body construction and auth flow until all tests pass.

- [ ] **Step 3: Fix any test failures**

Common issues:
- Multipart body signing: The HMAC signature must cover the raw multipart body bytes. If `authorize_public_request` rejects the signature, ensure `build_auth_headers` receives the exact body bytes sent in the request.
- SQLite LargeBinary: SQLite stores `LargeBinary` as BLOB which works fine for test.
- Pydantic validation: Ensure `MediaDerivativeRequest` model validation matches the error code mapping in the route handler.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_media_derivatives.py
git commit -m "feat: add media derivative API integration tests"
```

---

## Task 11: Worker + Processor Unit Tests

**Files:**
- Create: `tests/workers/test_media_derivative_worker.py`

- [ ] **Step 1: Create `tests/workers/test_media_derivative_worker.py`**

```python
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from app.domain.media_derivatives.contracts import MAX_PIXEL_COUNT
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
)
from app.domain.media_derivatives.processor import process_media_derivative


def _make_png_bytes(width: int = 100, height: int = 80, mode: str = "RGB") -> bytes:
    img = Image.new(mode, (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def test_process_webp_success() -> None:
    source = _make_png_bytes(200, 160)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="webp",
        max_width=100,
        quality=80,
    )
    assert result.format == "webp"
    assert result.mime_type == "image/webp"
    assert result.width == 100
    assert result.height == 80
    assert result.filesize_bytes > 0
    assert result.checksum.startswith("sha256:")
    actual_checksum = hashlib.sha256(result.output_bytes).hexdigest()
    assert result.checksum == f"sha256:{actual_checksum}"


def test_process_jpeg_flattens_alpha() -> None:
    source = _make_png_bytes(50, 50, mode="RGBA")
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="jpeg",
        max_width=50,
        quality=80,
    )
    assert result.format == "jpeg"
    assert "source_alpha_flattened_for_jpeg" in result.processing_warnings


def test_process_original_preserves_bytes() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="original",
        max_width=100,
        quality=80,
    )
    assert result.output_bytes == source
    assert result.width == 50
    assert result.height == 50


def test_process_no_resize_when_within_max_width() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=100,
        quality=80,
    )
    assert result.width == 50
    assert result.height == 50


def test_source_decode_failed() -> None:
    with pytest.raises(MediaDerivativeSourceDecodeFailedError):
        process_media_derivative(
            source_bytes=b"not an image",
            source_media_type="image",
            target_format="webp",
            max_width=100,
            quality=80,
        )


def test_animated_source_rejected() -> None:
    source = _make_animated_gif_bytes()
    with pytest.raises(MediaDerivativeAnimatedSourceUnavailableError):
        process_media_derivative(
            source_bytes=source,
            source_media_type="image",
            target_format="webp",
            max_width=100,
            quality=80,
        )


def test_pixel_bomb_protection() -> None:
    source = _make_png_bytes(1, 1)
    from unittest.mock import patch

    with patch("app.domain.media_derivatives.processor.MAX_PIXEL_COUNT", 1):
        with pytest.raises(MediaDerivativeSourceTooLargeError):
            process_media_derivative(
                source_bytes=source,
                source_media_type="image",
                target_format="webp",
                max_width=100,
                quality=80,
            )


def test_avif_unavailable_returns_explicit_error() -> None:
    source = _make_png_bytes(50, 50)
    with pytest.raises(MediaDerivativeFormatUnavailableError) as exc_info:
        process_media_derivative(
            source_bytes=source,
            source_media_type="image",
            target_format="avif",
            max_width=50,
            quality=80,
        )
    assert "avif" in str(exc_info.value.error_code).lower() or "avif" in str(exc_info.value.message).lower()


def test_processor_closes_image_handles() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=50,
        quality=80,
    )
    assert result.output_bytes is not None
```

- [ ] **Step 2: Run the processor tests**

Run: `python -m pytest tests/workers/test_media_derivative_worker.py -x -v`
Expected: Most tests pass. The AVIF test may need adjustment depending on whether Pillow in the test environment supports AVIF.

- [ ] **Step 3: Commit**

```bash
git add tests/workers/test_media_derivative_worker.py
git commit -m "feat: add media derivative worker and processor tests"
```

---

## Task 12: Run Full Test Suite + Lint

**Files:**
- None (verification only)

- [ ] **Step 1: Run linting**

Run: `ruff check app/ tests/`
Expected: No errors.

- [ ] **Step 2: Run type checking**

Run: `mypy app/`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=120`
Expected: All tests pass, including new media derivative tests and existing runtime tests.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address lint/type/test issues from media derivative implementation"
```
