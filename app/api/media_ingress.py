from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import BinaryIO

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.auth import authorize_public_request
from app.core.security import PrehashedRequestBody, RequestAuthContext, RequestAuthError

MEDIA_INGRESS_CHUNK_BYTES = 64 * 1024
MEDIA_INGRESS_MAX_REQUEST_BYTES = 64 * 1024
MEDIA_INGRESS_MAX_FIELDS = 1
MEDIA_INGRESS_MAX_FILES = 1
MEDIA_INGRESS_MAX_PART_HEADER_BYTES = 16 * 1024
MEDIA_INGRESS_MAX_CONTENT_LENGTH_DIGITS = 32
MEDIA_INGRESS_ALLOWED_PARTS = frozenset(
    {
        "request",
        "file",
    }
)


class MediaIngressError(ValueError):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class SealedRequestBodyCapture:
    def __init__(self, request: Request, *, max_body_bytes: int) -> None:
        self._request = request
        self._max_body_bytes = max_body_bytes
        self._body_file: BinaryIO | None = None
        self._evidence: PrehashedRequestBody | None = None
        self._load_started = False
        self._sealed = False
        self._closed = False

    @property
    def evidence(self) -> PrehashedRequestBody:
        if not self._sealed or self._evidence is None:
            raise RuntimeError("request body capture is not sealed")
        return self._evidence

    async def load_evidence(self) -> PrehashedRequestBody:
        if self._sealed and self._evidence is not None:
            return self._evidence
        if self._closed:
            raise RuntimeError("request body capture is closed")
        if self._load_started:
            raise RuntimeError("request body capture is already loading")
        self._load_started = True

        try:
            _validated_content_length(
                self._request,
                max_body_bytes=self._max_body_bytes,
            )
            self._body_file = tempfile.TemporaryFile("w+b")
            digest = hashlib.sha256()
            byte_size = 0
            async for chunk in self._request.stream():
                if not chunk:
                    continue
                byte_size += len(chunk)
                if byte_size > self._max_body_bytes:
                    raise _payload_too_large_error()
                digest.update(chunk)
                written = await run_in_threadpool(self._body_file.write, chunk)
                if written != len(chunk):
                    raise OSError("temporary media ingress storage short write")
            await run_in_threadpool(self._body_file.flush)
            self._evidence = PrehashedRequestBody(
                sha256_hex=digest.hexdigest(),
                byte_size=byte_size,
            )
            self._sealed = True
            return self._evidence
        except OSError as error:
            try:
                self.close()
            except BaseException:
                pass
            raise _ingress_storage_error() from error
        except BaseException:
            try:
                self.close()
            except BaseException:
                pass
            raise

    async def iter_chunks(self) -> AsyncGenerator[bytes, None]:
        body_file = self._require_sealed_file()
        try:
            await run_in_threadpool(body_file.seek, 0)
            while True:
                chunk = await run_in_threadpool(
                    body_file.read,
                    MEDIA_INGRESS_CHUNK_BYTES,
                )
                if not chunk:
                    return
                yield chunk
        except OSError as error:
            raise _ingress_storage_error() from error

    async def read_once(self, max_bytes: int) -> bytes:
        body_file = self._require_sealed_file()
        try:
            await run_in_threadpool(body_file.seek, 0)
            return await run_in_threadpool(body_file.read, max_bytes)
        except OSError as error:
            raise _ingress_storage_error() from error

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._body_file is not None:
            self._body_file.close()

    def _require_sealed_file(self) -> BinaryIO:
        if not self._sealed or self._body_file is None or self._closed:
            raise RuntimeError("request body capture is not available for replay")
        return self._body_file


class BoundedMultiPartParser(MultiPartParser):
    def __init__(
        self,
        headers: Headers,
        stream: AsyncGenerator[bytes, None],
        *,
        max_files: int | float,
        max_fields: int | float,
        max_part_size: int,
    ) -> None:
        super().__init__(
            headers,
            stream,
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )
        self.complete = False
        self._part_header_bytes = 0

    @property
    def tracked_files(self) -> tuple[tempfile.SpooledTemporaryFile[bytes], ...]:
        return tuple(self._files_to_close_on_error)

    def on_part_begin(self) -> None:
        self._part_header_bytes = 0
        super().on_part_begin()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._add_part_header_bytes(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._add_part_header_bytes(end - start)
        super().on_header_value(data, start, end)

    def on_end(self) -> None:
        self.complete = True
        super().on_end()

    def _add_part_header_bytes(self, byte_count: int) -> None:
        self._part_header_bytes += byte_count
        if self._part_header_bytes > MEDIA_INGRESS_MAX_PART_HEADER_BYTES:
            raise MultiPartException("Multipart part headers exceeded the accepted size limit.")


@dataclass(slots=True)
class MediaIngress:
    auth: RequestAuthContext
    request_json: str
    file: UploadFile | None
    _capture: SealedRequestBodyCapture
    _form_data: FormData | None = None
    _tracked_files: tuple[tempfile.SpooledTemporaryFile[bytes], ...] = ()
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        if self._form_data is not None:
            try:
                await self._form_data.close()
            except BaseException as error:
                first_error = error
            form_error = _close_form_uploads(self._form_data)
            if first_error is None:
                first_error = form_error
        tracked_error = _close_file_objects(self._tracked_files)
        if first_error is None:
            first_error = tracked_error
        try:
            self._capture.close()
        except BaseException as error:
            if first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error


def _payload_too_large_error() -> RequestAuthError:
    return RequestAuthError(
        413,
        "auth.payload_too_large",
        "request payload exceeds the accepted size limit",
    )


def _ingress_storage_error() -> MediaIngressError:
    return MediaIngressError(
        503,
        "media_upload.ingress_unavailable",
        "temporary media ingress storage is unavailable",
    )


def _validated_content_length(request: Request, *, max_body_bytes: int) -> int | None:
    raw_value = request.headers.get("content-length")
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or not value.isascii() or not value.isdigit():
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "Content-Length header must be a nonnegative decimal",
        )
    normalized_value = value.lstrip("0") or "0"
    max_body_value = str(max_body_bytes)
    if len(normalized_value) > len(max_body_value) or (
        len(normalized_value) == len(max_body_value) and normalized_value > max_body_value
    ):
        raise _payload_too_large_error()
    if len(value) > MEDIA_INGRESS_MAX_CONTENT_LENGTH_DIGITS:
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "Content-Length header exceeds the accepted length",
        )
    return int(normalized_value)


async def _read_json_body(
    capture: SealedRequestBodyCapture,
    *,
    byte_size: int,
) -> str:
    if byte_size > MEDIA_INGRESS_MAX_REQUEST_BYTES:
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "request JSON exceeds the accepted size limit",
        )
    payload = await capture.read_once(MEDIA_INGRESS_MAX_REQUEST_BYTES + 1)
    if len(payload) > MEDIA_INGRESS_MAX_REQUEST_BYTES:
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "request JSON exceeds the accepted size limit",
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "request JSON must be UTF-8 encoded",
        ) from error


def _close_form_uploads(form_data: FormData) -> BaseException | None:
    first_error: BaseException | None = None
    for _, value in form_data.multi_items():
        if isinstance(value, UploadFile) and not value.file.closed:
            try:
                value.file.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
    return first_error


def _close_file_objects(
    file_objects: tuple[tempfile.SpooledTemporaryFile[bytes], ...],
) -> BaseException | None:
    first_error: BaseException | None = None
    for file_object in file_objects:
        if not file_object.closed:
            try:
                file_object.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
    return first_error


def _close_parser_uploads(parser: BoundedMultiPartParser | None) -> None:
    if parser is not None:
        _close_file_objects(parser.tracked_files)


async def _parse_multipart(
    request: Request,
    capture: SealedRequestBodyCapture,
) -> tuple[
    str,
    UploadFile | None,
    FormData,
    tuple[tempfile.SpooledTemporaryFile[bytes], ...],
]:
    parser: BoundedMultiPartParser | None = None
    form_data: FormData | None = None
    try:
        parser = BoundedMultiPartParser(
            headers=request.headers,
            stream=capture.iter_chunks(),
            max_fields=MEDIA_INGRESS_MAX_FIELDS,
            max_files=MEDIA_INGRESS_MAX_FILES,
            max_part_size=MEDIA_INGRESS_MAX_REQUEST_BYTES,
        )
        form_data = await parser.parse()
        if not parser.complete:
            raise MediaIngressError(
                400,
                "media_upload.invalid_request",
                "multipart body is incomplete",
            )

        parts: dict[str, str | UploadFile] = {}
        for name, value in form_data.multi_items():
            if name not in MEDIA_INGRESS_ALLOWED_PARTS:
                raise MediaIngressError(
                    400,
                    "media_upload.invalid_request",
                    f"unsupported multipart part: {name}",
                )
            if name in parts:
                raise MediaIngressError(
                    400,
                    "media_upload.invalid_request",
                    f"duplicate multipart part: {name}",
                )
            parts[name] = value

        request_json = parts.get("request")
        if request_json is not None and not isinstance(request_json, str):
            raise MediaIngressError(
                400,
                "media_upload.invalid_request",
                "multipart request part must be a field",
            )
        if isinstance(request_json, str) and len(request_json.encode("utf-8")) > (
            MEDIA_INGRESS_MAX_REQUEST_BYTES
        ):
            raise MediaIngressError(
                400,
                "media_upload.invalid_request",
                "request JSON exceeds the accepted size limit",
            )

        upload_file = parts.get("file")
        if upload_file is not None and not isinstance(upload_file, UploadFile):
            raise MediaIngressError(
                400,
                "media_upload.invalid_request",
                "multipart file part must be a file",
            )

        return (
            request_json or "",
            upload_file,
            form_data,
            parser.tracked_files,
        )
    except MediaIngressError:
        if form_data is not None:
            _close_form_uploads(form_data)
        _close_parser_uploads(parser)
        raise
    except OSError as error:
        if form_data is not None:
            _close_form_uploads(form_data)
        _close_parser_uploads(parser)
        raise _ingress_storage_error() from error
    except Exception as error:
        if form_data is not None:
            _close_form_uploads(form_data)
        _close_parser_uploads(parser)
        raise MediaIngressError(
            400,
            "media_upload.invalid_request",
            "multipart body is invalid",
        ) from error
    except BaseException:
        if form_data is not None:
            _close_form_uploads(form_data)
        _close_parser_uploads(parser)
        raise


async def receive_media_ingress(
    request: Request,
    *,
    max_body_bytes: int,
) -> MediaIngress | JSONResponse:
    capture = SealedRequestBodyCapture(request, max_body_bytes=max_body_bytes)
    form_data: FormData | None = None
    tracked_files: tuple[tempfile.SpooledTemporaryFile[bytes], ...] = ()
    try:
        auth = await authorize_public_request(
            request,
            require_idempotency=True,
            required_scope="runtime:execute",
            max_body_bytes=max_body_bytes,
            body_evidence_loader=capture.load_evidence,
        )
        if isinstance(auth, JSONResponse):
            try:
                capture.close()
            except BaseException:
                pass
            return auth

        evidence = capture.evidence
        content_type = request.headers.get("content-type", "")
        if len(content_type.encode("utf-8")) > MEDIA_INGRESS_MAX_PART_HEADER_BYTES:
            raise MediaIngressError(
                400,
                "media_upload.invalid_request",
                "Content-Type header exceeds the accepted size limit",
            )
        media_type = content_type.partition(";")[0].strip().lower()
        if media_type == "multipart/form-data":
            (
                request_json,
                upload_file,
                form_data,
                tracked_files,
            ) = await _parse_multipart(
                request,
                capture,
            )
        else:
            request_json = await _read_json_body(
                capture,
                byte_size=evidence.byte_size,
            )
            upload_file = None

        return MediaIngress(
            auth=auth,
            request_json=request_json,
            file=upload_file,
            _capture=capture,
            _form_data=form_data,
            _tracked_files=tracked_files,
        )
    except BaseException:
        if form_data is not None:
            _close_form_uploads(form_data)
        _close_file_objects(tracked_files)
        try:
            capture.close()
        except BaseException:
            pass
        raise
