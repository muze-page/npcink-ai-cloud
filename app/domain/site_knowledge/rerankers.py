from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class SiteKnowledgeRerankError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(slots=True)
class RerankOutcome:
    results: list[dict[str, object]]
    metadata: dict[str, object]


class SiteKnowledgeReranker(Protocol):
    def rerank(self, *, query: str, results: list[dict[str, object]]) -> RerankOutcome:
        ...


def build_site_knowledge_reranker(settings: Settings) -> SiteKnowledgeReranker | None:
    provider = str(settings.site_knowledge_rerank_provider or "disabled").strip().lower()
    if provider == "disabled":
        return None
    if provider == "jina":
        return JinaSiteKnowledgeReranker(settings)
    raise SiteKnowledgeRerankError(
        "site_knowledge.rerank_provider_unsupported",
        f"site knowledge rerank provider '{provider}' is not supported",
    )


class JinaSiteKnowledgeReranker:
    def __init__(self, settings: Settings) -> None:
        api_key = str(settings.site_knowledge_jina_api_key or "").strip()
        base_url = str(settings.site_knowledge_jina_base_url or "").strip().rstrip("/")
        model = str(settings.site_knowledge_jina_rerank_model or "").strip()
        if not api_key or not base_url or not model:
            raise SiteKnowledgeRerankError(
                "site_knowledge.jina_rerank_config_missing",
                "Jina API key, base URL, and rerank model are required",
            )
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = float(settings.site_knowledge_rerank_timeout_seconds)
        self.top_k = max(1, int(settings.site_knowledge_rerank_top_k))

    def rerank(self, *, query: str, results: list[dict[str, object]]) -> RerankOutcome:
        candidates = results[: self.top_k]
        if len(candidates) <= 1:
            return RerankOutcome(
                results=results,
                metadata={
                    "status": "skipped",
                    "provider": "jina",
                    "model": self.model,
                    "candidate_count": len(candidates),
                    "reason": "not_enough_candidates",
                },
            )

        documents = [_document_text(candidate) for candidate in candidates]
        try:
            response = httpx.post(
                f"{self.base_url}/v1/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "return_documents": False,
                    "top_n": len(documents),
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise SiteKnowledgeRerankError(
                "site_knowledge.jina_rerank_failed",
                "Jina rerank request failed",
            ) from error

        ranked_items = _parse_jina_results(payload.get("results"), candidate_count=len(candidates))
        reranked_candidates: list[dict[str, object]] = []
        seen: set[int] = set()
        for index, score in ranked_items:
            seen.add(index)
            candidate = dict(candidates[index])
            candidate["reranked"] = True
            candidate["rerank_provider"] = "jina"
            candidate["rerank_model"] = self.model
            candidate["rerank_score"] = round(score, 4)
            reranked_candidates.append(candidate)

        for index, candidate in enumerate(candidates):
            if index in seen:
                continue
            fallback_candidate = dict(candidate)
            fallback_candidate["reranked"] = False
            reranked_candidates.append(fallback_candidate)

        return RerankOutcome(
            results=[*reranked_candidates, *results[len(candidates) :]],
            metadata={
                "status": "succeeded",
                "provider": "jina",
                "model": self.model,
                "candidate_count": len(candidates),
                "reranked_count": len(reranked_candidates),
            },
        )


def _document_text(result: dict[str, object]) -> str:
    title = str(result.get("title") or "").strip()
    context = str(result.get("match_context") or result.get("chunk") or "").strip()
    return "\n".join(part for part in (title, context) if part)


def _parse_jina_results(value: Any, *, candidate_count: int) -> list[tuple[int, float]]:
    if not isinstance(value, list):
        raise SiteKnowledgeRerankError(
            "site_knowledge.jina_rerank_invalid_response",
            "Jina rerank response did not include results",
        )
    ranked: list[tuple[int, float]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"), default=-1)
        if index < 0 or index >= candidate_count:
            continue
        ranked.append(
            (
                index,
                _coerce_float(item.get("relevance_score"), default=0.0),
            )
        )
    if not ranked:
        raise SiteKnowledgeRerankError(
            "site_knowledge.jina_rerank_invalid_response",
            "Jina rerank response did not include valid result indexes",
        )
    ranked.sort(key=lambda item: -item[1])
    return ranked


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
