from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import httpx


_PRICING_ROW_PATTERN = re.compile(
    r'<a href="https://cloud\.siliconflow\.cn/models\?target=([^"]+)"[^>]*>([^<]+)</a></div><div class="flex-1">([^<]+)</div><div class="flex-1">([^<]+)</div>',
    re.I,
)
_TARGET_MODEL_PATTERN = re.compile(r'\\"targetModelName\\":\\"([^\\]+)\\"')


class SiliconFlowRecognitionEvidenceImporter:
    def __init__(
        self,
        *,
        pricing_url: str = "https://www2.siliconflow.cn/pricing",
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        cny_per_usd: float = 7.2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.pricing_url = pricing_url.strip()
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.cny_per_usd = cny_per_usd if cny_per_usd > 0 else 7.2
        self.transport = transport

    def fetch_upstream_evidence_payload(self) -> dict[str, Any]:
        if not self.pricing_url:
            raise RuntimeError("siliconflow recognition pricing_url is required")
        try:
            with self._build_client() as client:
                response = client.get(self.pricing_url)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("siliconflow recognition evidence refresh timed out") from error
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "siliconflow recognition evidence refresh failed with "
                f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(
                f"siliconflow recognition evidence refresh network error: {error}"
            ) from error

        pricing_html = response.text
        pricing_rows = _extract_pricing_rows(pricing_html)
        embedded_metadata = _extract_embedded_metadata(pricing_html)
        if not pricing_rows and not embedded_metadata:
            raise ValueError("siliconflow pricing page returned no parseable model rows")

        generated_at = _serialize_timestamp(datetime.now(UTC))
        revision = str(
            response.headers.get("etag")
            or response.headers.get("last-modified")
            or generated_at
        )
        records: dict[str, dict[str, Any]] = {}
        for model_id in sorted(set(pricing_rows.keys()) | set(embedded_metadata.keys())):
            record = self._build_record(
                model_id=model_id,
                generated_at=generated_at,
                pricing=pricing_rows.get(model_id, {}),
                metadata=embedded_metadata.get(model_id, {}),
            )
            if record is None:
                continue
            record_key, record_payload = record
            records[record_key] = record_payload

        return {
            "version": "recognition_upstream_v1",
            "generated_at": generated_at,
            "sources": {
                "siliconflow_snapshot": revision,
            },
            "records": records,
        }

    def _build_record(
        self,
        *,
        model_id: str,
        generated_at: str,
        pricing: dict[str, Any],
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]] | None:
        normalized_model_id = str(model_id or "").strip()
        if not normalized_model_id:
            return None
        shape = _derive_shape(
            model_id=normalized_model_id,
            model_type=str(metadata.get("type") or "").strip().lower(),
            model_sub_type=str(metadata.get("sub_type") or "").strip().lower(),
            vlm=bool(metadata.get("vlm")),
            function_call_support=bool(metadata.get("function_call_support")),
            json_mode_support=bool(metadata.get("json_mode_support")),
        )
        display_name = (
            str(metadata.get("display_name") or "").strip()
            or str(pricing.get("display_name") or "").strip()
            or normalized_model_id.split("/")[-1]
        )
        stripped_model_id = _strip_siliconflow_variant_prefix(normalized_model_id)
        price_input = _normalize_cny_price_to_usd(
            pricing.get("price_input_cny"),
            cny_per_usd=self.cny_per_usd,
        )
        price_output = _normalize_cny_price_to_usd(
            pricing.get("price_output_cny"),
            cny_per_usd=self.cny_per_usd,
        )
        aliases = _unique_strings(
            [
                normalized_model_id,
                stripped_model_id,
                display_name,
                stripped_model_id.split("/")[-1],
                display_name.replace(" (Free)", "").replace(" (Pro)", "").strip(),
            ]
        )
        return (
            f"siliconflow::{normalized_model_id}",
            {
                "provider": "siliconflow",
                "model_id": normalized_model_id,
                "aliases": aliases,
                "match_keys": _unique_strings(
                    aliases
                    + [
                        f"siliconflow/{normalized_model_id}",
                        f"siliconflow:{normalized_model_id}",
                        f"siliconflow/{stripped_model_id}",
                        f"siliconflow:{stripped_model_id}",
                    ]
                ),
                "evidence_source": "siliconflow_pricing_page",
                "model_type": shape["model_type"],
                "preview_type": shape["preview_type"],
                "input_modalities": shape["input_modalities"],
                "output_modalities": shape["output_modalities"],
                "capabilities": shape["capabilities"],
                "confidence": shape["confidence"],
                "price_input": price_input,
                "price_output": price_output,
                "source_details": {
                    "siliconflow_pricing_page": {
                        "provider": "siliconflow",
                        "model_id": normalized_model_id,
                        "model_type": shape["model_type"],
                        "preview_type": shape["preview_type"],
                        "capabilities": shape["capabilities"],
                        "confidence": shape["confidence"],
                        "price_input": price_input,
                        "price_output": price_output,
                        "price_source": "siliconflow_pricing_page_cny",
                        "price_updated_at": generated_at,
                        "price_confidence": 0.88,
                    }
                },
            },
        )

    def _build_client(self) -> httpx.Client:
        headers = {
            "User-Agent": self.app_name,
        }
        return httpx.Client(
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
            follow_redirects=True,
        )

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "unknown error"
        if isinstance(payload, dict):
            error = str(payload.get("error") or payload.get("message") or "").strip()
            if error:
                return error
        return response.text or "unknown error"


def _extract_pricing_rows(value: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for match in _PRICING_ROW_PATTERN.finditer(value):
        model_id = unquote(match.group(1)).strip()
        if not model_id:
            continue
        rows[model_id] = {
            "display_name": html.unescape(match.group(2)).strip(),
            "price_input_cny": _parse_cny_amount(match.group(3)),
            "price_output_cny": _parse_cny_amount(match.group(4)),
        }
    return rows


def _extract_embedded_metadata(value: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for match in _TARGET_MODEL_PATTERN.finditer(value):
        model_id = unquote(match.group(1)).strip()
        if not model_id:
            continue
        start = max(0, match.start() - 2000)
        end = min(len(value), match.end() + 800)
        window = value[start:end]
        rows[model_id] = {
            "display_name": _pick_escaped_string(window, r'\\"DisplayName\\":\\"([^\\]+)\\"'),
            "type": _pick_escaped_string(window, r'\\"type\\":\\"([^\\]+)\\"'),
            "sub_type": _pick_escaped_string(window, r'\\"subType\\":\\"([^\\]+)\\"'),
            "context_len": _pick_escaped_int(window, r'\\"contextLen\\":(\d+)'),
            "json_mode_support": _pick_escaped_bool(window, r'\\"jsonModeSupport\\":(true|false)'),
            "function_call_support": _pick_escaped_bool(window, r'\\"functionCallSupport\\":(true|false)'),
            "vlm": _pick_escaped_bool(window, r'\\"vlm\\":(true|false)'),
        }
    return rows


def _pick_escaped_string(value: str, pattern: str) -> str:
    match = re.search(pattern, value)
    return html.unescape(match.group(1)).strip() if match else ""


def _pick_escaped_int(value: str, pattern: str) -> int | None:
    match = re.search(pattern, value)
    return int(match.group(1)) if match else None


def _pick_escaped_bool(value: str, pattern: str) -> bool:
    match = re.search(pattern, value)
    return bool(match and match.group(1) == "true")


def _parse_cny_amount(value: str) -> float | None:
    normalized = html.unescape(str(value or "")).strip().lower()
    if not normalized:
        return None
    if normalized in {"免费", "free"}:
        return 0.0
    normalized = normalized.replace("元", "").replace("/ m tokens", "").replace(",", "").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


def _normalize_cny_price_to_usd(value: Any, *, cny_per_usd: float) -> float | None:
    if value is None:
        return None
    amount = float(value)
    if amount == 0:
        return 0.0
    return round(amount / max(cny_per_usd, 0.001), 6)


def _strip_siliconflow_variant_prefix(model_id: str) -> str:
    normalized = str(model_id or "").strip()
    if normalized.startswith("Pro/"):
        return normalized.split("/", 1)[1]
    return normalized


def _derive_shape(
    *,
    model_id: str,
    model_type: str,
    model_sub_type: str,
    vlm: bool,
    function_call_support: bool,
    json_mode_support: bool,
) -> dict[str, Any]:
    normalized = f"{model_id} {model_type} {model_sub_type}".lower()
    if "embedding" in normalized or "rerank" in normalized:
        return {
            "model_type": "embedding",
            "preview_type": "embedding",
            "input_modalities": ["text"],
            "output_modalities": ["embedding"],
            "capabilities": {
                "text_input": True,
                "image_input": False,
                "image_output": False,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.9,
        }
    if model_type in {"image", "video"} or model_sub_type in {
        "text-to-image",
        "image-to-image",
        "text-to-video",
        "image-to-video",
    } or any(token in normalized for token in ("flux", "sdxl", "stable-diffusion", "image")):
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "input_modalities": ["text", "image"] if "image-to-" in model_sub_type else ["text"],
            "output_modalities": ["image"],
            "capabilities": {
                "text_input": True,
                "image_input": "image-to-" in model_sub_type,
                "image_output": True,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.88,
        }
    if vlm or any(token in normalized for token in ("vision", "vl", "ocr")):
        return {
            "model_type": "vision",
            "preview_type": "text",
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "capabilities": {
                "text_input": True,
                "image_input": True,
                "image_output": False,
                "vision": True,
                "tools": function_call_support,
                "structured_output": json_mode_support,
            },
            "confidence": 0.9,
        }
    return {
        "model_type": "chat",
        "preview_type": "text",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "capabilities": {
            "text_input": True,
            "image_input": False,
            "image_output": False,
            "vision": False,
            "tools": function_call_support,
            "structured_output": json_mode_support,
        },
        "confidence": 0.86,
    }


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
