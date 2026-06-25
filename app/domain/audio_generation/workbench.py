from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.adapters.callbacks.base import RuntimeCallbackDispatcher
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.adapters.queue.base import RuntimeQueue
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import RunRecord
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_ABILITY_FAMILY,
    AUDIO_GENERATION_CLOUD_ABILITY,
    AUDIO_GENERATION_CONTRACT,
    AUDIO_GENERATION_EXECUTION_KIND,
)
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_PROFILE_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
)
from app.domain.routing.errors import RoutingError
from app.domain.runtime.errors import RuntimeErrorBase
from app.domain.runtime.models import RUNTIME_STORAGE_MODE_RESULT_ONLY, RuntimeRequest
from app.domain.runtime.service import (
    RuntimeResultExpiredError,
    RuntimeResultNotReadyError,
    RuntimeService,
)

ALLOWED_AUDIO_WORKBENCH_INTENTS = frozenset({"article_narration", "article_audio_summary"})
DEFAULT_AUDIO_WORKBENCH_SITE_ID = "site_smoke"
HOSTED_AI_CONTENT_SUPPORT_ABILITY = "npcink-toolbox/ai-content-support"
HOSTED_AI_CONTENT_SUPPORT_CONTRACT = "hosted_ai_content_support.v1"
AUDIO_SUMMARY_SCRIPT_INTENT = "audio_summary_script"
MAX_AUDIO_SCRIPT_CHARS = 4800
MAX_AUDIO_SOURCE_CHARS = 20000
ALLOWED_AUDIO_TEXT_PROFILE_IDS = frozenset({TEXT_AI_PROFILE_ID, FREE_GPT55_TEXT_PROFILE_ID})
ALLOWED_AUDIO_OUTPUT_PROFILE_IDS = frozenset(
    {AUDIO_NARRATION_PROFILE_ID, AUDIO_NARRATION_QUALITY_PROFILE_ID}
)
AUDIO_SUMMARY_SCRIPT_MAX_ATTEMPTS = 2
AUDIO_SUMMARY_SCRIPT_TRANSIENT_ERROR_CODES = frozenset(
    {
        "provider.timeout",
        "provider.network_error",
        "provider.rate_limited",
        "provider.upstream_unavailable",
        "provider.upstream_error",
    }
)


class AudioWorkbenchError(ValueError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, object]:
        return dict(self.details)


@dataclass(slots=True)
class AudioWorkbenchService:
    database_url: str
    settings: Settings
    providers: dict[str, ProviderAdapter]
    runtime_queue: RuntimeQueue | None = None
    callback_dispatcher: RuntimeCallbackDispatcher | None = None

    def create_job(self, payload: dict[str, Any]) -> dict[str, object]:
        request_payload = self._normalize_create_payload(payload)
        runtime_service = self._runtime_service()
        script_bundle = self._build_script_bundle(request_payload, runtime_service=runtime_service)
        audio_profile_id = self._audio_profile_id_for_intent(str(request_payload["intent"]))
        script_generation = _dict(script_bundle["generation"])
        runtime_request = RuntimeRequest(
            site_id=str(request_payload["site_id"]),
            ability_name=AUDIO_GENERATION_CLOUD_ABILITY,
            ability_family=AUDIO_GENERATION_ABILITY_FAMILY,
            contract_version=AUDIO_GENERATION_CONTRACT,
            channel="admin",
            execution_kind=AUDIO_GENERATION_EXECUTION_KIND,
            profile_id=audio_profile_id,
            execution_tier="cloud",
            execution_pattern="whole_run_offload",
            data_classification="internal",
            storage_mode=RUNTIME_STORAGE_MODE_RESULT_ONLY,
            timeout_seconds=max(1, int(float(self.settings.minimax_timeout_seconds or 30))),
            retry_max=0,
            retention_ttl=86400,
            task_backend={
                "enabled": True,
                "mode": "queue",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 2,
            },
            input_payload={
                "contract_version": AUDIO_GENERATION_CONTRACT,
                "intent": str(request_payload["intent"]),
                "script": script_bundle["text"],
                "format": str(request_payload["format"]),
                "response_format": "url",
                "language_boost": "auto",
                "article_context": {
                    "title": str(request_payload["title"]),
                    "source_chars": len(str(request_payload["body"])),
                    "script_source": script_bundle["source"],
                    "script_generation_present": bool(script_generation.get("run_id")),
                    "audio_profile_id": audio_profile_id,
                },
            },
            policy={"allow_fallback": False},
            idempotency_key=f"admin-audio-{uuid4().hex}",
            trace_id=f"admin-audio-{uuid4().hex}",
        )
        result = runtime_service.execute(runtime_request)
        return self._job_payload(
            result,
            site_id=str(request_payload["site_id"]),
            script_bundle=script_bundle,
        )

    def get_job(self, run_id: str) -> dict[str, object]:
        runtime_service = self._runtime_service()
        run = runtime_service.get_run(run_id)
        payload: dict[str, object] = {
            "run_id": run["run_id"],
            "status": run["status"],
            "site_id": run["site_id"],
            "trace_id": run["trace_id"],
            "provider_id": run["provider_id"],
            "model_id": run["model_id"],
            "instance_id": run["instance_id"],
            "profile_id": run["profile_id"],
            "error_code": run["error_code"],
            "error_message": run["error_message"],
            "task_backend": run["task_backend"],
            "run_lifecycle": run["run_lifecycle"],
            "result_ready": False,
            "result": {},
            "boundary": self._boundary(),
        }
        try:
            result = runtime_service.get_run_result(run_id)
            payload["result_ready"] = True
            payload["result"] = result.get("result", {})
        except RuntimeResultNotReadyError:
            pass
        except RuntimeResultExpiredError as error:
            payload["error_code"] = error.error_code
            payload["error_message"] = error.message
        return payload

    def list_recent_jobs(self, *, limit: int = 10) -> dict[str, object]:
        max_items = max(1, min(20, int(limit)))
        with get_session(self.database_url) as session:
            runs = list(
                session.scalars(
                    select(RunRecord)
                    .where(
                        RunRecord.ability_name == AUDIO_GENERATION_CLOUD_ABILITY,
                        RunRecord.channel == "admin",
                    )
                    .order_by(RunRecord.started_at.desc(), RunRecord.run_id.desc())
                    .limit(max_items)
                )
            )

        return {
            "contract_version": "admin_audio_workbench_recent_runs.v1",
            "limit": max_items,
            "items": [_recent_audio_run_summary(run) for run in runs],
            "boundary": self._boundary(),
        }

    def process_one_queued_job(self) -> None:
        self._runtime_service().process_next_queued_run(timeout_seconds=0)

    def _runtime_service(self) -> RuntimeService:
        return RuntimeService(
            self.database_url,
            settings=self.settings,
            providers=resolve_execution_provider_adapters(
                self.settings,
                base_providers=self.providers,
            ),
            runtime_queue=self.runtime_queue,
            callback_dispatcher=self.callback_dispatcher,
            callback_max_attempts=self.settings.runtime_callback_max_attempts,
            callback_retry_backoff_seconds=self.settings.runtime_callback_retry_backoff_seconds,
        )

    def _normalize_create_payload(self, payload: dict[str, Any]) -> dict[str, object]:
        intent = str(payload.get("intent") or "article_narration").strip()
        if intent not in ALLOWED_AUDIO_WORKBENCH_INTENTS:
            raise AudioWorkbenchError(
                "audio_workbench.intent_invalid",
                "audio workbench intent must be article_narration or article_audio_summary",
            )
        title = _compact_text(str(payload.get("title") or ""))[:180]
        body = _clean_article_text(str(payload.get("body") or ""))[:MAX_AUDIO_SOURCE_CHARS]
        site_id = str(payload.get("site_id") or DEFAULT_AUDIO_WORKBENCH_SITE_ID).strip()
        audio_format = str(payload.get("format") or "mp3").strip().lower()
        if audio_format not in {"mp3", "wav", "pcm"}:
            raise AudioWorkbenchError(
                "audio_workbench.format_invalid",
                "audio format must be mp3, wav, or pcm",
            )
        if not body:
            raise AudioWorkbenchError(
                "audio_workbench.body_required",
                "article text is required",
            )
        if not site_id:
            raise AudioWorkbenchError(
                "audio_workbench.site_required",
                "site_id is required",
            )
        return {
            "intent": intent,
            "title": title,
            "body": body,
            "site_id": site_id,
            "format": audio_format,
            "script_source": (
                "full_article" if intent == "article_narration" else AUDIO_SUMMARY_SCRIPT_INTENT
            ),
        }

    def _build_script_bundle(
        self,
        payload: dict[str, object],
        *,
        runtime_service: RuntimeService,
    ) -> dict[str, object]:
        intent = str(payload["intent"])
        title = str(payload["title"])
        body = str(payload["body"])
        if intent == "article_audio_summary":
            return self._build_audio_summary_script_bundle(
                payload,
                runtime_service=runtime_service,
            )
        parts = [title, body] if title else [body]
        script = _compact_text("\n\n".join(parts))[:MAX_AUDIO_SCRIPT_CHARS]
        return {
            "source": "full_article",
            "text": script,
            "characters": len(script),
            "generation": {
                "mode": "direct_article_text",
                "intent": "article_narration",
                "audio_profile_id": self._audio_profile_id_for_intent("article_narration"),
            },
            "output_json": {},
        }

    def _build_audio_summary_script_bundle(
        self,
        payload: dict[str, object],
        *,
        runtime_service: RuntimeService,
    ) -> dict[str, object]:
        prompt = _build_audio_summary_script_prompt(
            title=str(payload["title"]),
            excerpt="",
            body=str(payload["body"]),
        )
        last_issue: dict[str, object] = {}
        for attempt in range(1, AUDIO_SUMMARY_SCRIPT_MAX_ATTEMPTS + 1):
            request = self._audio_summary_script_request(
                payload,
                prompt=prompt,
                attempt=attempt,
            )
            try:
                response = runtime_service.execute(request)
            except (RuntimeErrorBase, RoutingError) as error:
                last_issue = _audio_summary_issue_from_exception(error, attempt=attempt)
                if _should_retry_audio_summary_issue(last_issue, attempt=attempt):
                    continue
                raise _audio_summary_workbench_error(last_issue) from error

            failed_issue = _audio_summary_issue_from_response(response, attempt=attempt)
            if failed_issue:
                last_issue = failed_issue
                if _should_retry_audio_summary_issue(last_issue, attempt=attempt):
                    continue
                raise _audio_summary_workbench_error(last_issue)

            output = response.result if isinstance(response.result, dict) else {}
            output_text = str(output.get("output_text") or "").strip()
            output_json = _decode_json_object_from_text(output_text)
            if output_text.startswith("[hosted:") or (
                output_json and not _has_audio_summary_script_shape(output_json)
            ):
                last_issue = _audio_summary_issue(
                    reason="unsupported_shape",
                    attempt=attempt,
                    retryable=False,
                    run_id=response.run_id,
                    trace_id=response.trace_id,
                    provider_id=response.provider_id,
                    model_id=response.model_id,
                )
                raise _audio_summary_workbench_error(last_issue)

            script = _audio_summary_script_text(output_json, fallback=output_text)
            if not script:
                last_issue = _audio_summary_issue(
                    reason="empty_output",
                    attempt=attempt,
                    retryable=True,
                    run_id=response.run_id,
                    trace_id=response.trace_id,
                    provider_id=response.provider_id,
                    model_id=response.model_id,
                )
                if _should_retry_audio_summary_issue(last_issue, attempt=attempt):
                    continue
                raise _audio_summary_workbench_error(last_issue)

            script = script[:MAX_AUDIO_SCRIPT_CHARS]
            return {
                "source": AUDIO_SUMMARY_SCRIPT_INTENT,
                "intent": AUDIO_SUMMARY_SCRIPT_INTENT,
                "text": script,
                "characters": len(script),
                "generation": {
                    "mode": "hosted_ai_content_support",
                    "ability_name": HOSTED_AI_CONTENT_SUPPORT_ABILITY,
                    "contract_version": HOSTED_AI_CONTENT_SUPPORT_CONTRACT,
                    "run_id": response.run_id,
                    "trace_id": response.trace_id,
                    "provider_id": response.provider_id,
                    "model_id": response.model_id,
                    "profile_id": response.profile_id,
                    "status": response.status,
                    "attempts": attempt,
                    "retry_attempted": attempt > 1,
                },
                "output_json": output_json,
                "quality_contract": _audio_summary_quality_contract(),
            }

        raise _audio_summary_workbench_error(last_issue)

    def _audio_summary_script_request(
        self,
        payload: dict[str, object],
        *,
        prompt: str,
        attempt: int,
    ) -> RuntimeRequest:
        trace_id = f"admin-audio-script-{uuid4().hex}"
        return RuntimeRequest(
            site_id=str(payload["site_id"]),
            ability_name=HOSTED_AI_CONTENT_SUPPORT_ABILITY,
            ability_family="text",
            contract_version=HOSTED_AI_CONTENT_SUPPORT_CONTRACT,
            channel="admin",
            execution_kind="text",
            profile_id=self._audio_summary_text_profile_id(),
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            storage_mode=RUNTIME_STORAGE_MODE_RESULT_ONLY,
            timeout_seconds=30,
            retry_max=0,
            retention_ttl=86400,
            task_backend={"enabled": False},
            input_payload={
                "contract_version": HOSTED_AI_CONTENT_SUPPORT_CONTRACT,
                "intent": AUDIO_SUMMARY_SCRIPT_INTENT,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are Npcink Toolbox. Return only compact JSON "
                            "audio summary script candidates. No markdown, no "
                            "commentary, no WordPress writes."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "params": {
                    "temperature": 0.45,
                    "max_tokens": 900,
                },
                "quality_contract": _audio_summary_quality_contract(),
                "workbench_retry": {
                    "attempt": attempt,
                    "max_attempts": AUDIO_SUMMARY_SCRIPT_MAX_ATTEMPTS,
                },
            },
            policy={"allow_fallback": False},
            idempotency_key=f"admin-audio-script-{uuid4().hex}",
            trace_id=trace_id,
        )

    def _audio_summary_text_profile_id(self) -> str:
        value = str(self.settings.audio_summary_text_profile_id or "").strip()
        return value if value in ALLOWED_AUDIO_TEXT_PROFILE_IDS else TEXT_AI_PROFILE_ID

    def _audio_profile_id_for_intent(self, intent: str) -> str:
        if intent == "article_audio_summary":
            value = str(self.settings.audio_summary_audio_profile_id or "").strip()
        else:
            value = str(self.settings.audio_narration_profile_id or "").strip()
        return value if value in ALLOWED_AUDIO_OUTPUT_PROFILE_IDS else AUDIO_NARRATION_PROFILE_ID

    def _job_payload(
        self,
        result: Any,
        *,
        site_id: str,
        script_bundle: dict[str, object],
    ) -> dict[str, object]:
        return {
            "run_id": result.run_id,
            "status": result.status,
            "trace_id": result.trace_id,
            "site_id": site_id,
            "provider_id": result.provider_id,
            "model_id": result.model_id,
            "instance_id": result.instance_id,
            "profile_id": result.profile_id,
            "script": {
                **script_bundle,
            },
            "task_backend": result.task_backend,
            "run_lifecycle": result.run_lifecycle,
            "result_ready": result.status == "succeeded",
            "result": result.result if result.status == "succeeded" else {},
            "boundary": self._boundary(),
        }

    def _boundary(self) -> dict[str, object]:
        return {
            "owner": "cloud_runtime",
            "direct_wordpress_write": False,
            "final_writes": "core_proposal_required",
            "artifact_type": "audio_generation_candidates",
        }


def _clean_article_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", unescape(value or ""))
    return _compact_text(text)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _recent_audio_run_summary(run: RunRecord) -> dict[str, object]:
    input_payload = run.input_json if isinstance(run.input_json, dict) else {}
    result_payload = run.result_json if isinstance(run.result_json, dict) else {}
    article_context = _dict(input_payload.get("article_context"))
    audio_summary = _recent_audio_artifact_summary(result_payload)
    return {
        "run_id": run.run_id,
        "site_id": run.site_id,
        "status": run.status,
        "intent": str(input_payload.get("intent") or "audio_generation"),
        "script_source": str(article_context.get("script_source") or ""),
        "provider_id": run.selected_provider_id or "",
        "model_id": run.selected_model_id or "",
        "instance_id": run.selected_instance_id or "",
        "profile_id": run.profile_id,
        "trace_id": run.trace_id,
        "error_code": run.error_code or "",
        "error_message": _compact_text(run.error_message or "")[:180],
        "started_at": _isoformat_or_empty(run.started_at),
        "finished_at": _isoformat_or_empty(run.finished_at),
        "duration_seconds": audio_summary["duration_seconds"],
        "audio_ready": audio_summary["audio_ready"],
        "mime_type": audio_summary["mime_type"],
        "direct_wordpress_write": bool(result_payload.get("direct_wordpress_write", False)),
    }


def _recent_audio_artifact_summary(result_payload: dict[str, Any]) -> dict[str, object]:
    audio = _first_dict(result_payload.get("audios"))
    return {
        "audio_ready": bool(audio.get("url") or audio.get("b64_json")),
        "duration_seconds": float(audio.get("duration_seconds") or 0.0),
        "mime_type": str(audio.get("mime_type") or ""),
    }


def _first_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    for item in value:
        if isinstance(item, dict):
            return item
    return {}


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _isoformat_or_empty(value: Any) -> str:
    return value.isoformat() if value else ""


def _audio_summary_issue(
    *,
    reason: str,
    attempt: int,
    retryable: bool,
    error_code: str = "",
    error_message: str = "",
    run_id: str = "",
    trace_id: str = "",
    provider_id: str = "",
    model_id: str = "",
) -> dict[str, object]:
    return {
        "reason": reason,
        "attempt": attempt,
        "max_attempts": AUDIO_SUMMARY_SCRIPT_MAX_ATTEMPTS,
        "retryable": retryable,
        "retry_attempted": attempt > 1,
        "upstream_error_code": error_code,
        "upstream_error_message": _compact_text(error_message)[:240],
        "run_id": run_id,
        "trace_id": trace_id,
        "provider_id": provider_id,
        "model_id": model_id,
    }


def _audio_summary_issue_from_exception(
    error: RuntimeErrorBase | RoutingError,
    *,
    attempt: int,
) -> dict[str, object]:
    error_code = str(getattr(error, "error_code", "") or "")
    reason = _audio_summary_reason_for_error_code(error_code)
    return _audio_summary_issue(
        reason=reason,
        attempt=attempt,
        retryable=_audio_summary_error_retryable(error_code),
        error_code=error_code,
        error_message=str(getattr(error, "message", "") or ""),
    )


def _audio_summary_issue_from_response(response: Any, *, attempt: int) -> dict[str, object]:
    if str(getattr(response, "status", "") or "") != "failed":
        return {}
    error_code = str(getattr(response, "error_code", "") or "")
    return _audio_summary_issue(
        reason=_audio_summary_reason_for_error_code(error_code),
        attempt=attempt,
        retryable=bool(getattr(response, "retryable", False))
        or _audio_summary_error_retryable(error_code),
        error_code=error_code,
        error_message=str(getattr(response, "error_message", "") or ""),
        run_id=str(getattr(response, "run_id", "") or ""),
        trace_id=str(getattr(response, "trace_id", "") or ""),
        provider_id=str(getattr(response, "provider_id", "") or ""),
        model_id=str(getattr(response, "model_id", "") or ""),
    )


def _audio_summary_reason_for_error_code(error_code: str) -> str:
    if error_code in {"routing.no_candidates", "routing.profile_not_found"}:
        return "text_profile_unavailable"
    if error_code in {
        "provider.auth_invalid",
        "provider.access_denied",
        "provider.quota_exceeded",
        "runtime.provider_not_configured",
    }:
        return "text_provider_not_ready"
    if error_code in AUDIO_SUMMARY_SCRIPT_TRANSIENT_ERROR_CODES:
        return "transient_provider_error"
    return "script_generation_failed"


def _audio_summary_error_retryable(error_code: str) -> bool:
    return error_code in AUDIO_SUMMARY_SCRIPT_TRANSIENT_ERROR_CODES


def _should_retry_audio_summary_issue(issue: dict[str, object], *, attempt: int) -> bool:
    return bool(issue.get("retryable")) and attempt < AUDIO_SUMMARY_SCRIPT_MAX_ATTEMPTS


def _audio_summary_workbench_error(issue: dict[str, object]) -> AudioWorkbenchError:
    reason = str(issue.get("reason") or "script_generation_failed")
    message_by_reason = {
        "text_profile_unavailable": (
            "Audio summary needs a ready text model before audio can be generated. "
            "Open AI resources, select a ready text profile, then try again."
        ),
        "text_provider_not_ready": (
            "The selected text model connection is not ready. Check the text provider "
            "in AI resources, then try again."
        ),
        "transient_provider_error": (
            "The text model was temporarily unavailable while creating the audio "
            "summary script. I retried once and it still failed. Please try again "
            "in a moment."
        ),
        "empty_output": (
            "The text model returned an empty audio summary script. I retried once; "
            "try again, or switch to Article narration if you need audio immediately."
        ),
        "unsupported_shape": (
            "The text model returned a response that is not usable as an audio "
            "summary script. Check the selected text model, then try again."
        ),
        "script_generation_failed": (
            "Audio summary script generation failed before audio could be created. "
            "Check AI resources and try again."
        ),
    }
    action_by_reason = {
        "text_profile_unavailable": "configure_text_profile",
        "text_provider_not_ready": "check_text_provider",
        "transient_provider_error": "retry_later",
        "empty_output": "retry_or_use_narration",
        "unsupported_shape": "check_text_model",
        "script_generation_failed": "check_ai_resources",
    }
    error_code_by_reason = {
        "text_profile_unavailable": "audio_workbench.summary_text_profile_unavailable",
        "text_provider_not_ready": "audio_workbench.summary_text_provider_not_ready",
        "transient_provider_error": "audio_workbench.summary_script_provider_temporary_failure",
        "empty_output": "audio_workbench.summary_script_empty",
        "unsupported_shape": "audio_workbench.summary_script_unusable",
        "script_generation_failed": "audio_workbench.summary_script_failed",
    }
    details = dict(issue)
    details["action"] = action_by_reason.get(reason, "check_ai_resources")
    details["stage"] = "audio_summary_script"
    return AudioWorkbenchError(
        error_code_by_reason.get(reason, "audio_workbench.summary_script_failed"),
        message_by_reason.get(reason, message_by_reason["script_generation_failed"]),
        details=details,
    )


def _audio_summary_quality_contract() -> dict[str, object]:
    return {
        "output_shape": {
            "script": (
                "one listenable 1 to 3 minute audio summary script grounded only "
                "in supplied draft context"
            ),
            "opening": "short spoken opening that names the topic directly",
            "key_points": "3 to 5 concise spoken points",
            "closing": (
                "short closing that helps the listener decide whether to read the full article"
            ),
            "assumptions_to_verify": "short list, only when the source is ambiguous",
        },
        "review_checklist": [
            "Use the same language as the source draft.",
            "Make the output sound natural when read aloud.",
            "Keep the script grounded in the supplied draft and do not add new facts.",
            "Do not claim to publish, upload media, insert audio, or change WordPress content.",
        ],
    }


def _build_audio_summary_script_prompt(*, title: str, excerpt: str, body: str) -> str:
    payload = {
        "task": (
            "Generate only a concise spoken audio summary script for the current article. "
            "The listener should understand the core topic, the main value, 3 to 5 "
            "important points, and whether to read the full article. Use natural speech, "
            "not archive excerpt copy. Do not rewrite the article, do not add unsupported "
            "facts, and do not include WordPress write instructions."
        ),
        "intent": AUDIO_SUMMARY_SCRIPT_INTENT,
        "source": {
            "title": title,
            "excerpt": excerpt,
            "content": body,
            "summary_generation_mode": "full_context",
        },
        "quality_contract": _audio_summary_quality_contract(),
        "preferred_output_shape": _audio_summary_quality_contract()["output_shape"],
        "output_requirements": [
            (
                "Return one compact JSON object with script, opening, key_points, "
                "closing, and assumptions_to_verify."
            ),
            "Do not wrap the JSON in markdown fences.",
            (
                "Make script natural to hear aloud, about 250 to 550 Chinese "
                "characters or 120 to 260 English words depending on source language."
            ),
            (
                "Compress the whole draft into a listening summary; do not produce "
                "a full article rewrite or a short WordPress excerpt."
            ),
            "Return reviewable suggestions only.",
            "Do not write or publish WordPress content.",
        ],
        "boundary": {
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
            "final_writes": "core_proposal_required",
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_json_object_from_text(text: str) -> dict[str, object]:
    trimmed = text.strip()
    if not trimmed:
        return {}
    direct = _try_json_object(trimmed)
    if direct:
        return direct
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", trimmed, flags=re.S)
    if fenced:
        parsed = _try_json_object(fenced.group(1))
        if parsed:
            return parsed
    bracketed = re.search(r"(\{.*\})", trimmed, flags=re.S)
    if bracketed:
        parsed = _try_json_object(bracketed.group(1))
        if parsed:
            return parsed
    return {}


def _try_json_object(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_audio_summary_script_shape(output_json: dict[str, object]) -> bool:
    return any(key in output_json for key in ("script", "opening", "key_points", "closing"))


def _audio_summary_script_text(output_json: dict[str, object], *, fallback: str) -> str:
    parts: list[str] = []
    for key in ("opening", "script", "closing"):
        value = _compact_text(str(output_json.get(key) or ""))
        if value:
            parts.append(value)
    key_points = output_json.get("key_points")
    if isinstance(key_points, list):
        for point in key_points[:5]:
            value = _compact_text(str(point or ""))
            if value:
                parts.append(value)
    script = _compact_text("\n\n".join(dict.fromkeys(parts)))
    if script:
        return script
    return _compact_text(fallback)
