from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, unquote

import httpx

from app.model_intelligence.publisher.utils import (
    build_checksum,
    build_price_summary,
    html_decode,
    infer_price_tier,
    now_iso,
    unique_strings,
)

DEFAULT_PRICING_URL = "https://www2.siliconflow.cn/pricing"
FALLBACK_PRICING_URL = "https://cloud-rd.siliconflow.cn/pricing"
PRICING_ROW_PATTERN = re.compile(
    r'<a href="https://cloud\.siliconflow\.cn/models\?target=([^"]+)"[^>]*>([^<]+)</a></div><div class="flex-1">([^<]+)</div><div class="flex-1">([^<]+)</div>',
    re.I,
)
TARGET_MODEL_PATTERN = re.compile(r'\\"targetModelName\\":\\"([^\\]+)\\"')
PRICE_DEVIATION_THRESHOLD = 0.50


class PriceCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 300.0,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(60.0, recovery_timeout_seconds)
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.is_open = False

    def record_success(self) -> None:
        self.failure_count = 0
        self.last_failure_time = None
        self.is_open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = __import__("time").time()
        if self.failure_count >= self.failure_threshold:
            self.is_open = True

    def should_allow(self) -> bool:
        if not self.is_open:
            return True
        if self.last_failure_time is not None:
            elapsed = __import__("time").time() - self.last_failure_time
            if elapsed >= self.recovery_timeout_seconds:
                self.is_open = False
                self.failure_count = 0
                return True
        return False


class SiliconFlowPublisherSource:
    id = "siliconflow"

    def __init__(
        self,
        *,
        pricing_url: str = DEFAULT_PRICING_URL,
        cny_per_usd: float = 7.2,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
        circuit_breaker: PriceCircuitBreaker | None = None,
        price_history: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.pricing_url = pricing_url
        self.cny_per_usd = cny_per_usd if cny_per_usd > 0 else 7.2
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport
        self.circuit_breaker = circuit_breaker or PriceCircuitBreaker()
        self.price_history = price_history or {}

    def fetch_bundle(self) -> dict[str, Any]:
        if not self.circuit_breaker.should_allow():
            raise RuntimeError("siliconflow circuit breaker is open")

        fetched_at = now_iso()
        errors: list[str] = []
        pricing_rows: dict[str, dict[str, Any]] = {}
        embedded_metadata: dict[str, dict[str, Any]] = {}
        resolved_pricing_url = self.pricing_url
        with httpx.Client(
            headers={"user-agent": self.app_name},
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            for candidate_url in build_candidate_pricing_urls(self.pricing_url):
                try:
                    response = client.get(candidate_url)
                    response.raise_for_status()
                except Exception as error:
                    errors.append(f"{candidate_url}: {error}")
                    self.circuit_breaker.record_failure()
                    continue
                pricing_html = response.text
                pricing_rows = extract_pricing_rows(pricing_html)
                embedded_metadata = extract_embedded_metadata(pricing_html)
                if pricing_rows or embedded_metadata:
                    resolved_pricing_url = candidate_url
                    break
                errors.append(f"{candidate_url}: siliconflow pricing page returned no parseable model rows")
        model_ids = sorted(set(pricing_rows.keys()) | set(embedded_metadata.keys()))
        if not model_ids:
            self.circuit_breaker.record_failure()
            raise RuntimeError("; ".join(errors) or "siliconflow pricing page returned no parseable model rows")

        models: list[dict[str, Any]] = []
        anomaly_count = 0
        for model_id in model_ids:
            model = build_siliconflow_model(
                model_id=model_id,
                fetched_at=fetched_at,
                cny_per_usd=self.cny_per_usd,
                pricing=pricing_rows.get(model_id, {}),
                metadata=embedded_metadata.get(model_id, {}),
                pricing_url=resolved_pricing_url,
            )
            if self._is_price_anomaly(model):
                anomaly_count += 1
                errors.append(f"{model_id}: price anomaly detected")
                continue
            models.append(model)

        total_models = len(model_ids)
        if total_models > 0 and anomaly_count / total_models > 0.30:
            self.circuit_breaker.record_failure()
            raise RuntimeError(
                f"siliconflow price anomaly rate {anomaly_count}/{total_models} exceeds 30% threshold"
            )

        self.circuit_breaker.record_success()
        self._update_price_history(models)

        bundle_core = {
            "bundle_kind": "model_intelligence_bundle_v1",
            "schema_version": "model_intelligence_bundle_v1",
            "generated_at": fetched_at,
            "sources": [
                {
                    "source_id": self.id,
                    "source_type": "provider_catalog",
                    "status": "success",
                    "fetched_at": fetched_at,
                    "source_url": resolved_pricing_url,
                    "records_total": len(models),
                }
            ],
            "models": models,
        }
        return {**bundle_core, "checksum": build_checksum(bundle_core)}

    def _is_price_anomaly(self, model: dict[str, Any]) -> bool:
        model_id = str(model.get("model_id") or "").strip()
        if not model_id or model_id not in self.price_history:
            return False
        history = self.price_history[model_id]
        current_input = float(model.get("price_input") or 0.0)
        current_output = float(model.get("price_output") or 0.0)
        hist_input = float(history.get("price_input") or 0.0)
        hist_output = float(history.get("price_output") or 0.0)
        if hist_input > 0 and current_input > 0:
            if abs(current_input - hist_input) / hist_input > PRICE_DEVIATION_THRESHOLD:
                return True
        if hist_output > 0 and current_output > 0:
            if abs(current_output - hist_output) / hist_output > PRICE_DEVIATION_THRESHOLD:
                return True
        return False

    def _update_price_history(self, models: list[dict[str, Any]]) -> None:
        for model in models:
            model_id = str(model.get("model_id") or "").strip()
            if not model_id:
                continue
            self.price_history[model_id] = {
                "price_input": float(model.get("price_input") or 0.0),
                "price_output": float(model.get("price_output") or 0.0),
                "updated_at": now_iso(),
            }


def build_candidate_pricing_urls(pricing_url: str) -> list[str]:
    normalized = str(pricing_url or "").strip() or DEFAULT_PRICING_URL
    candidates = [normalized]
    if normalized == DEFAULT_PRICING_URL:
        candidates.append(FALLBACK_PRICING_URL)
    elif normalized == FALLBACK_PRICING_URL:
        candidates.append(DEFAULT_PRICING_URL)
    return unique_strings(candidates)


def extract_pricing_rows(html: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for match in PRICING_ROW_PATTERN.finditer(html):
        model_id = unquote(match.group(1) or "").strip()
        if not model_id:
            continue
        rows[model_id] = {
            "display_name": html_decode(match.group(2)),
            "price_input_cny": parse_cny(match.group(3)),
            "price_output_cny": parse_cny(match.group(4)),
        }
    return rows


def extract_embedded_metadata(html: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for match in TARGET_MODEL_PATTERN.finditer(html):
        model_id = unquote(match.group(1) or "").strip()
        if not model_id:
            continue
        start = max(0, match.start() - 2000)
        end = min(len(html), match.end() + 1200)
        window = html[start:end]
        rows[model_id] = {
            "display_name": pick_escaped_string(window, r'\\"DisplayName\\":\\"([^\\]+)\\"'),
            "type": pick_escaped_string(window, r'\\"type\\":\\"([^\\]+)\\"'),
            "sub_type": pick_escaped_string(window, r'\\"subType\\":\\"([^\\]+)\\"'),
            "context_len": pick_escaped_int(window, r'\\"contextLen\\":(\d+)'),
            "json_mode_support": pick_escaped_bool(window, r'\\"jsonModeSupport\\":(true|false)'),
            "function_call_support": pick_escaped_bool(window, r'\\"functionCallSupport\\":(true|false)'),
            "vlm": pick_escaped_bool(window, r'\\"vlm\\":(true|false)'),
        }
    return rows


def build_siliconflow_model(
    *,
    model_id: str,
    fetched_at: str,
    cny_per_usd: float,
    pricing: dict[str, Any],
    metadata: dict[str, Any],
    pricing_url: str,
) -> dict[str, Any]:
    normalized_model_id = str(model_id or "").strip()
    normalized_name = strip_variant_prefix(normalized_model_id)
    shape = derive_shape(
        model_id=normalized_model_id,
        model_type=str(metadata.get("type") or "").strip().lower(),
        model_sub_type=str(metadata.get("sub_type") or "").strip().lower(),
        vlm=bool(metadata.get("vlm")),
        function_call_support=bool(metadata.get("function_call_support")),
        json_mode_support=bool(metadata.get("json_mode_support")),
    )
    price_input = normalize_cny_to_usd(pricing.get("price_input_cny"), cny_per_usd)
    price_output = normalize_cny_to_usd(pricing.get("price_output_cny"), cny_per_usd)
    has_exact_price = price_input is not None or price_output is not None
    price_reference_kind = "exact" if has_exact_price else "unavailable"
    price_tier = infer_price_tier(price_input, price_output) if has_exact_price else infer_estimated_tier(shape["supports"])
    display_name = (
        str(metadata.get("display_name") or "").strip()
        or str(pricing.get("display_name") or "").strip()
        or normalized_name.split("/")[-1]
        or normalized_name
    )
    description = build_description(shape["model_type"])
    return {
        "provider": "siliconflow",
        "model_id": normalized_model_id,
        "display_name": display_name,
        "model_type": shape["model_type"],
        "preview_type": shape["preview_type"],
        "supports": shape["supports"],
        "capability_profile": shape["model_type"],
        "aliases": unique_strings([normalized_model_id, normalized_name, display_name]),
        "source_ids": ["siliconflow"],
        "price_reference_kind": price_reference_kind,
        "price_input": price_input,
        "price_output": price_output,
        "price_tier": price_tier,
        "price_summary": build_price_summary(
            kind=price_reference_kind,
            price_input=price_input,
            price_output=price_output,
            tier=price_tier,
        ),
        "short_description": description["short_description"],
        "best_for": description["best_for"],
        "why_recommended": "来自 SiliconFlow 公开模型目录与价格页的定时汇聚结果。",
        "updated_at": fetched_at,
        "source_url": f"{pricing_url}#{quote(normalized_model_id, safe='')}",
        "metadata": {
            "source": "siliconflow",
            "context_len": metadata.get("context_len"),
        },
    }


def strip_variant_prefix(model_id: str) -> str:
    return model_id[4:] if model_id.startswith("Pro/") else model_id


def derive_shape(
    *,
    model_id: str,
    model_type: str,
    model_sub_type: str,
    vlm: bool,
    function_call_support: bool,
    json_mode_support: bool,
) -> dict[str, Any]:
    normalized = f"{model_id} {model_type} {model_sub_type}".lower()
    if any(token in normalized for token in ("embedding", "rerank", "bge")):
        return {"model_type": "embedding", "preview_type": "embedding", "supports": ["embedding"]}
    if model_type in {"image", "video"} or model_sub_type in {
        "text-to-image",
        "image-to-image",
        "text-to-video",
        "image-to-video",
    } or any(token in normalized for token in ("flux", "sdxl", "stable-diffusion", "image")):
        return {"model_type": "image_generation", "preview_type": "image", "supports": ["text", "image_generation"]}
    if vlm or any(token in normalized for token in ("vision", "ocr", "vl")):
        return {
            "model_type": "vision",
            "preview_type": "text",
            "supports": unique_strings(
                [
                    "text",
                    "vision",
                    "tools" if function_call_support else "",
                    "structured" if json_mode_support else "",
                ]
            ),
        }
    return {
        "model_type": "chat",
        "preview_type": "text",
        "supports": unique_strings(
            ["text", "tools" if function_call_support else "", "structured" if json_mode_support else ""]
        ),
    }


def infer_estimated_tier(supports: list[str]) -> str:
    if "embedding" in supports:
        return "low"
    if "image_generation" in supports:
        return "high"
    return "medium"


def build_description(model_type: str) -> dict[str, str]:
    if model_type == "embedding":
        return {"short_description": "适合向量检索、召回和相似度计算。", "best_for": "知识库检索与语义搜索"}
    if model_type == "image_generation":
        return {"short_description": "适合文本生图和图像生成工作流。", "best_for": "海报、配图与创意图像生成"}
    if model_type == "vision":
        return {"short_description": "适合图文理解、视觉问答和 OCR 场景。", "best_for": "图像理解与视觉问答"}
    return {"short_description": "适合通用文本对话、写作和推理任务。", "best_for": "通用问答、写作与推理"}


def parse_cny(value: Any) -> float | None:
    normalized = html_decode(value).strip().lower()
    if not normalized:
        return None
    if normalized in {"免费", "free"}:
        return 0.0
    cleaned = normalized.replace("元", "").replace("/ m tokens", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_cny_to_usd(value: Any, cny_per_usd: float) -> float | None:
    if value is None:
        return None
    amount = float(value)
    if amount == 0:
        return 0.0
    return round(amount / max(cny_per_usd, 0.001), 6)


def pick_escaped_string(value: str, pattern: str) -> str:
    match = re.search(pattern, value)
    return html_decode(match.group(1)).strip() if match else ""


def pick_escaped_int(value: str, pattern: str) -> int | None:
    match = re.search(pattern, value)
    return int(match.group(1)) if match else None


def pick_escaped_bool(value: str, pattern: str) -> bool:
    match = re.search(pattern, value)
    return bool(match and match.group(1) == "true")
