from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, unquote_plus, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"
REDACTION_FAILED = "[redaction_failed]"
TRUNCATED_DEPTH = "[truncated:max_depth]"
TRUNCATED_ITEMS = "[truncated:max_items]"

DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_ITEMS = 64
DEFAULT_MAX_TEXT_CHARS = 4096
MAX_TEXT_SCAN_CHARS = 16_384

_SAFE_IDENTIFIER_KEYS = frozenset(
    {
        "account_id",
        "ability_name",
        "ability_family",
        "channel",
        "error_code",
        "error_stage",
        "event_kind",
        "instance_id",
        "key_id",
        "model_id",
        "profile_id",
        "provider_id",
        "run_id",
        "site_id",
        "trace_id",
        "tokens_in",
        "tokens_out",
    }
)
_EXACT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "database_url",
        "dsn",
        "encryption_key",
        "jwt",
        "key",
        "password",
        "private_key",
        "provider_key",
        "redis_url",
        "secret",
        "set_cookie",
        "signature",
        "signing_key",
        "smtp_password",
    }
)
_SENSITIVE_KEY_COMPONENTS = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "jwt",
        "passwd",
        "password",
        "passwords",
        "secret",
        "secrets",
        "signature",
        "signatures",
        "token",
        "tokens",
    }
)
_CONTENT_KEYS = frozenset(
    {
        "body",
        "content",
        "contents",
        "email_body",
        "error_message",
        "input",
        "input_payload",
        "message",
        "message_body",
        "messages",
        "output",
        "output_text",
        "payload",
        "prompt",
        "prompts",
        "raw_result",
        "request_body",
        "request_payload",
        "response_body",
        "response_payload",
        "result",
        "result_json",
        "support_message",
    }
)
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "code",
        "cookie",
        "credential",
        "jwt",
        "key",
        "password",
        "refresh_token",
        "session",
        "session_id",
        "secret",
        "sig",
        "signature",
        "state",
        "ticket",
        "token",
        "x_amz_credential",
        "x_amz_security_token",
        "x_amz_signature",
        "x_goog_credential",
        "x_goog_signature",
    }
)
_DSN_SCHEMES = frozenset(
    {
        "amqp",
        "amqps",
        "mariadb",
        "mongodb",
        "mongodb+srv",
        "mysql",
        "postgres",
        "postgresql",
        "postgresql+psycopg",
        "redis",
        "rediss",
        "smtp",
        "smtps",
    }
)
_CREDENTIAL_PATH_MARKERS = frozenset(
    {
        "access",
        "auth",
        "authorization",
        "bearer",
        "credential",
        "download_token",
        "jwt",
        "key",
        "password",
        "presigned",
        "secret",
        "signature",
        "signed",
        "token",
    }
)

_NORMALIZE_KEY_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_ACRONYM_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>{}\[\]\"']+", re.IGNORECASE)
_AUTHORIZATION_HEADER_RE = re.compile(
    r"\b(?P<name>authorization|proxy[-_]authorization)\s*[:=]\s*(?P<value>[^\r\n]*)",
    re.IGNORECASE,
)
_COOKIE_HEADER_RE = re.compile(
    r"\b(?P<name>cookie|set-cookie)\s*[:=]\s*[^\r\n]*",
    re.IGNORECASE,
)
_QUERY_PAIR_RE = re.compile(
    r"(?P<prefix>[?&;])(?P<key>[A-Za-z0-9_.~%+\-]{1,256})="
    r"(?P<value>[^&#;\s]*)",
    re.IGNORECASE,
)
_NAMED_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<name>[A-Za-z][A-Za-z0-9_.\-]{0,127})"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(?P<scheme>bearer|basic)\s+[^\s,;]+", re.IGNORECASE)
_JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_PROVIDER_KEY_RE = re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)
_OPAQUE_PATH_TOKEN_RE = re.compile(
    r"(?=.{16,256}\Z)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9._~-]+\Z"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_sensitive_key(key: str) -> str:
    separated = _CAMEL_ACRONYM_RE.sub(r"\1_\2", key.strip())
    separated = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _NORMALIZE_KEY_RE.sub("_", separated.lower()).strip("_")


def is_sensitive_key(key: str) -> bool:
    normalized = normalize_sensitive_key(key)
    if not normalized or normalized in _SAFE_IDENTIFIER_KEYS:
        return False
    if normalized in _EXACT_SENSITIVE_KEYS or normalized in _CONTENT_KEYS:
        return True
    components = frozenset(normalized.split("_"))
    if components & _SENSITIVE_KEY_COMPONENTS:
        return True
    if normalized.endswith("_api_key") or normalized.endswith("_access_key"):
        return True
    return False


def redact_sensitive(
    value: object,
    *,
    key: str = "",
    depth: int = 0,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> object:
    try:
        if key and is_sensitive_key(key):
            return REDACTED
        if depth >= max(1, max_depth):
            return TRUNCATED_DEPTH
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return redact_text(value, max_chars=max_text_chars)
        if isinstance(value, bytes):
            return "[redacted:bytes]"
        if isinstance(value, Mapping):
            sanitized: dict[str, object] = {}
            for index, (raw_key, item) in enumerate(value.items()):
                if index >= max(1, max_items):
                    sanitized["__truncated__"] = TRUNCATED_ITEMS
                    break
                safe_key = _safe_mapping_key(raw_key)
                sanitized[safe_key] = redact_sensitive(
                    item,
                    key=raw_key if isinstance(raw_key, str) else safe_key,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_text_chars=max_text_chars,
                )
            return sanitized
        if isinstance(value, list):
            items = [
                redact_sensitive(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_text_chars=max_text_chars,
                )
                for item in value[: max(1, max_items)]
            ]
            if len(value) > max(1, max_items):
                items.append(TRUNCATED_ITEMS)
            return items
        if isinstance(value, tuple):
            tuple_items = tuple(
                redact_sensitive(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_text_chars=max_text_chars,
                )
                for item in value[: max(1, max_items)]
            )
            if len(value) > max(1, max_items):
                return (*tuple_items, TRUNCATED_ITEMS)
            return tuple_items
        return REDACTED
    except BaseException:
        return REDACTION_FAILED


def redact_text(value: str, *, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    try:
        output_limit = min(max(1, int(max_chars)), MAX_TEXT_SCAN_CHARS)
        if len(value) > output_limit:
            return _truncate_text(f"{REDACTED}...[truncated]", max_chars=output_limit)

        sanitized = _URL_RE.sub(_redact_url_match, value)
        sanitized = _AUTHORIZATION_HEADER_RE.sub(_redact_authorization_header, sanitized)
        sanitized = _COOKIE_HEADER_RE.sub(
            lambda match: f"{match.group('name')}={REDACTED}",
            sanitized,
        )
        sanitized = _QUERY_PAIR_RE.sub(_redact_query_pair, sanitized)
        sanitized = _NAMED_VALUE_RE.sub(_redact_named_value, sanitized)
        sanitized = _BEARER_RE.sub(
            lambda match: f"{match.group('scheme').title()} {REDACTED}",
            sanitized,
        )
        sanitized = _JWT_RE.sub(REDACTED, sanitized)
        sanitized = _PROVIDER_KEY_RE.sub(REDACTED, sanitized)
        sanitized = _CONTROL_RE.sub(_escape_control, sanitized)
        return _truncate_text(sanitized, max_chars=output_limit)
    except BaseException:
        return REDACTION_FAILED


def safe_exception_type(error: BaseException | type[BaseException] | object) -> str:
    try:
        error_type = error if isinstance(error, type) else type(error)
        name = getattr(error_type, "__name__", "Exception")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            return "Exception"
        return name
    except BaseException:
        return "Exception"


def _safe_mapping_key(value: object) -> str:
    if isinstance(value, str):
        return _truncate_text(_CONTROL_RE.sub(_escape_control, value), max_chars=128)
    if isinstance(value, (bool, int, float)):
        return str(value)
    return "[redacted_key]"


def _redact_authorization_header(match: re.Match[str]) -> str:
    name = match.group("name")
    value = match.group("value").strip()
    scheme = value.split(None, 1)[0].lower() if value else ""
    if scheme in {"bearer", "basic"}:
        return f"{name}: {scheme.title()} {REDACTED}"
    return f"{name}: {REDACTED}"


def _redact_query_pair(match: re.Match[str]) -> str:
    query_key = match.group("key")
    try:
        normalized_key = normalize_sensitive_key(unquote_plus(query_key))
    except BaseException:
        return f"{match.group('prefix')}{query_key}={REDACTED}"
    if normalized_key in _CREDENTIAL_QUERY_KEYS or is_sensitive_key(normalized_key):
        return f"{match.group('prefix')}{query_key}={REDACTED}"
    return match.group(0)


def _redact_named_value(match: re.Match[str]) -> str:
    name = match.group("name")
    normalized_name = normalize_sensitive_key(name)
    if name.lower() in {
        "authorization",
        "proxy-authorization",
        "proxy_authorization",
        "cookie",
        "set-cookie",
    }:
        return match.group(0)
    if is_sensitive_key(normalized_name):
        return f"{name}={REDACTED}"
    return match.group(0)


def _redact_url_path(path: str) -> str:
    segments = path.split("/")
    redacted_segments: list[str] = []
    redact_next = False
    for raw_segment in segments:
        try:
            decoded_segment = unquote(raw_segment)
        except BaseException:
            decoded_segment = raw_segment
        normalized_segment = normalize_sensitive_key(decoded_segment)
        credential_marker = (
            normalized_segment in _CREDENTIAL_PATH_MARKERS
            or normalized_segment in _CREDENTIAL_QUERY_KEYS
        )
        credential_value = (
            redact_next
            or _JWT_RE.fullmatch(decoded_segment) is not None
            or _PROVIDER_KEY_RE.fullmatch(decoded_segment) is not None
            or _OPAQUE_PATH_TOKEN_RE.fullmatch(decoded_segment) is not None
        )
        redacted_segments.append(REDACTED if credential_value else raw_segment)
        redact_next = credential_marker
    return "/".join(redacted_segments)


def _redact_url_match(match: re.Match[str]) -> str:
    raw_url = match.group(0)
    suffix = ""
    while raw_url and raw_url[-1] in ".,);":
        suffix = raw_url[-1] + suffix
        raw_url = raw_url[:-1]
    try:
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme.lower()
        if scheme in _DSN_SCHEMES:
            return f"{scheme}://{REDACTED}{suffix}"
        hostname = parsed.hostname
        if not hostname:
            return f"[redacted-url]{suffix}"
        host = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        netloc = f"{host}:{port}" if port is not None else host
        query_items = []
        for query_key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
            normalized_key = normalize_sensitive_key(query_key)
            safe_value = (
                REDACTED
                if normalized_key in _CREDENTIAL_QUERY_KEYS or is_sensitive_key(query_key)
                else redact_text(query_value, max_chars=512)
            )
            query_items.append((query_key, safe_value))
        sanitized = urlunsplit(
            (
                parsed.scheme,
                netloc,
                _redact_url_path(parsed.path),
                urlencode(query_items, doseq=True),
                "",
            )
        )
        return sanitized + suffix
    except BaseException:
        return f"[redacted-url]{suffix}"


def _escape_control(match: re.Match[str]) -> str:
    value = match.group(0)
    if value == "\r":
        return "\\r"
    if value == "\n":
        return "\\n"
    if value == "\t":
        return "\\t"
    return "[control]"


def _truncate_text(value: str, *, max_chars: int) -> str:
    limit = max(1, int(max_chars))
    if len(value) <= limit:
        return value
    marker = "...[truncated]"
    if limit <= len(marker):
        return marker[-limit:]
    return f"{value[: limit - len(marker)]}{marker}"
