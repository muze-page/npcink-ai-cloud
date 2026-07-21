from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy.orm import Session

from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings
from app.domain.media_artifacts.input_loading import LoadedArtifactInput
from app.domain.runtime.errors import RuntimeExecutionContractError
from app.domain.site_knowledge.contracts import (
    SITE_KNOWLEDGE_CONTRACTS,
    SITE_KNOWLEDGE_SEARCH_ABILITY,
)
from app.domain.site_knowledge.repository import SiteKnowledgeRepository
from app.domain.site_knowledge.service import SiteKnowledgeService
from app.domain.wordpress_ai_connector.contracts import (
    WORDPRESS_OPERATION_CONTRACT,
    WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS,
    WP_AI_CONNECTOR_SOURCE_TEXT_TASKS,
    contains_inline_media_transport,
    resolve_site_knowledge_reference_mode,
)
from app.domain.wordpress_ai_connector.generation_context import (
    GENERATION_CONTEXT_CONTRACT,
    build_generation_context_pack,
    generation_context_policy,
    render_generation_context,
    select_generation_context_post_ids,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    resolve_wordpress_ai_connector_profile_spec,
)

EmbeddingUsageCallback = Callable[
    [str, ProviderExecutionRequest, ProviderExecutionResult | None, ProviderExecutionError | None],
    None,
]


class WordPressOperationRuntime:
    """Executes WordPress-specific provider preparation and result normalization."""

    def __init__(
        self,
        *,
        settings: Settings,
        providers: dict[str, ProviderAdapter],
    ) -> None:
        self.settings = settings
        self.providers = providers

    def source_artifact_id(self, input_payload: dict[str, Any]) -> str:
        operation_contract = self._dict_or_empty(input_payload.get("operation_contract"))
        if str(operation_contract.get("task") or "").strip() != "alt_text_suggest":
            return ""
        scene_request = self._dict_or_empty(operation_contract.get("request"))
        return str(scene_request.get("source_artifact_id") or "").strip()

    def build_provider_input(
        self,
        input_payload: dict[str, Any],
        *,
        source_artifact: LoadedArtifactInput | None = None,
    ) -> dict[str, Any]:
        operation_contract = self._dict_or_empty(input_payload.get("operation_contract"))
        scene_request = operation_contract.get("request")
        scene_request = scene_request if isinstance(scene_request, dict) else {}
        task = str(operation_contract.get("task") or "").strip()
        if task == "alt_text_suggest":
            if source_artifact is None:
                raise ValueError("alt text provider input requires loaded source artifact")
            return self._build_alt_text_provider_input(
                scene_request=scene_request,
                source_artifact=source_artifact,
            )

        scene_text = str(
            scene_request.get(
                "source_text" if task in WP_AI_CONNECTOR_SOURCE_TEXT_TASKS else "prompt"
            )
            or ""
        ).strip()
        raw_system_instruction = scene_request.get("system_instruction")
        if task in WP_AI_CONNECTOR_SOURCE_TEXT_TASKS:
            system_instruction = (
                raw_system_instruction.strip() if isinstance(raw_system_instruction, str) else ""
            )
        else:
            system_instruction = str(raw_system_instruction or "").strip()
        task_contract = self._dict_or_empty(scene_request.get("task_contract"))
        task_family = str(task_contract.get("task_family") or "").strip()
        raw_constraints = task_contract.get("constraints")
        constraint_items = raw_constraints if isinstance(raw_constraints, list) else []
        constraints = {
            str(item).strip()
            for item in constraint_items
            if isinstance(item, str) and str(item).strip()
        }

        task_instruction = {
            "alt_text_suggest": "Generate concise image alt text. Return only the alt text.",
            "comment_moderation": (
                "Classify the comment moderation outcome. Return strict JSON only. No markdown."
            ),
            "comment_reply_suggest": "Draft a concise comment reply. Return only the reply text.",
            "content_classification": (
                'Classify the content. Return strict JSON only: {"suggestions":'
                '[{"term":"...","confidence":0.8,"is_new":false}]}. No markdown.'
            ),
            "content_rewrite": (
                "Rewrite the content as requested. Return exactly one rewritten version."
            ),
            "content_summary": "Summarize the content. Return only the summary.",
            "excerpt_generation": "Generate a concise excerpt. Return only the excerpt.",
            "meta_description": (
                "Generate one SEO meta description, 120 to 155 characters. Return "
                "only the description."
            ),
            "title_generation": (
                "Generate exactly one concise title faithful to the main topic. For Chinese, "
                "normally use no more than 36 characters; for other languages, normally use "
                "no more than 12 words. Return only the title text."
            ),
        }.get(task)
        if task_instruction is None:
            task_instruction = {
                "generation": "Generate the requested value from the scene input.",
                "classification": (
                    "Classify the scene input according to the requested output schema."
                ),
                "transformation": "Transform the scene input as requested.",
                "analysis": "Analyze the scene input and return the requested result.",
            }.get(task_family, "Return only the requested suggestion. Do not explain.")

        fragments = [task_instruction]
        fragments.append(
            "Use the same language as the scene input unless a WordPress ability "
            "instruction explicitly asks for another language."
        )
        fragments.append(
            "Output contract: return only the final value for this one task. Do not "
            "include introductions, headings, Markdown, bullet lists, numbered lists, "
            "multiple options, labels, explanations, or offers to continue. Never add a "
            "name, number, claim, or event that is absent from the scene input."
        )
        if "json_object" in constraints:
            fragments.append(
                "Return one strict JSON object matching the Ability output schema. No markdown."
            )
            output_schema = self._dict_or_empty(task_contract.get("output_schema"))
            if output_schema:
                fragments.append(
                    "Ability output schema: "
                    + json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
                )
        if "single_value" in constraints:
            fragments.append("Return exactly one value, not a list of alternatives.")
        if "source_grounded" in constraints:
            fragments.append("Keep every factual claim grounded in the current scene input.")
        if "no_new_numbers" in constraints:
            fragments.append(
                "Do not introduce a number that is absent from the current scene input."
            )
        if "existing_terms_only" in constraints:
            fragments.append("Choose only from the supplied existing taxonomy candidates.")
        if task == "content_classification" and self._has_available_terms(scene_text):
            fragments.append(
                "The scene input includes <available-terms>. Choose only exact term names "
                "from that list and set is_new=false for every suggestion."
            )
        if system_instruction:
            fragments.append(system_instruction)
        if scene_text:
            fragments.append(f"Scene input:\n{scene_text}")
        fragments.append("Do not mention this instruction. Do not explain your answer.")

        provider_input: dict[str, Any] = {
            "input": "\n\n".join(fragments),
            "text": scene_text,
            "metadata": {
                "source_surface": "wordpress_ai_connector",
                "task": task,
                "ability_name": str(task_contract.get("ability_name") or ""),
                "task_family": task_family,
                "task_constraints": sorted(constraints),
                "suggestion_only": True,
            },
        }

        default_max_tokens = {
            "alt_text_suggest": 48,
            "comment_moderation": 120,
            "comment_reply_suggest": 180,
            "content_classification": 220,
            "content_rewrite": 512,
            "content_summary": 160,
            "excerpt_generation": 140,
            "meta_description": 80,
            "title_generation": 48,
        }.get(
            task,
            {
                "generation": 160,
                "classification": 220,
                "transformation": 512,
                "analysis": 220,
            }.get(task_family, 160),
        )

        max_tokens = self._coerce_int(scene_request.get("max_tokens"), default=0)
        if max_tokens <= 0:
            max_tokens = default_max_tokens
        if max_tokens > 0:
            provider_input["max_tokens"] = max_tokens
            provider_input["max_output_tokens"] = max_tokens

        temperature = scene_request.get("temperature")
        if isinstance(temperature, (int, float)):
            provider_input["temperature"] = float(temperature)

        return provider_input

    def apply_site_knowledge_reference(
        self,
        *,
        site_id: str,
        run_id: str,
        session: Session,
        input_payload: dict[str, Any],
        provider_input: dict[str, Any],
        embedding_usage_callback: EmbeddingUsageCallback,
    ) -> dict[str, Any]:
        operation_contract = self._dict_or_empty(input_payload.get("operation_contract"))
        scene_request = self._dict_or_empty(operation_contract.get("request"))
        reference = self._dict_or_empty(scene_request.get("site_knowledge_reference"))
        task = str(operation_contract.get("task") or "").strip()
        task_contract = self._dict_or_empty(scene_request.get("task_contract"))
        expected_mode = resolve_site_knowledge_reference_mode(
            task=task,
            task_contract=task_contract,
        )
        mode = str(reference.get("mode") or "")
        if not expected_mode or mode != expected_mode or reference.get("enabled") is not True:
            return provider_input

        policy = generation_context_policy(
            task=task,
            mode=mode,
            task_family=str(task_contract.get("task_family") or ""),
            context_requirements=task_contract.get("context_requirements"),
        )
        if policy is None:
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="task_policy_unavailable",
            )

        scene_text = str(
            scene_request.get(
                "source_text" if task in WP_AI_CONNECTOR_SOURCE_TEXT_TASKS else "prompt"
            )
            or ""
        ).strip()
        if not scene_text:
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="scene_input_empty",
            )

        try:
            result = SiteKnowledgeService(
                session,
                settings=self.settings,
                providers=self.providers,
                embedding_usage_callback=embedding_usage_callback,
            ).execute(
                site_id=site_id,
                ability_name=SITE_KNOWLEDGE_SEARCH_ABILITY,
                contract_version=SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                input_payload={
                    "contract_version": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                    "query": scene_text,
                    "intent": "writing_context",
                    "max_results": min(20, policy.max_source_posts * 2),
                    "filters": {
                        "post_types": ["post", "page"],
                        "status": ["publish"],
                        "source_types": ["post", "page"],
                    },
                    "evidence_policy": {
                        "min_score": policy.min_score,
                        "required_sources": 1,
                        "no_hit_policy": "fallback_to_general",
                    },
                    "write_posture": "suggestion_only",
                },
                run_id=run_id,
            )
        except Exception:
            # Optional references must never break the primary editor task.
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="retrieval_failed",
            )

        evidence_gate = self._dict_or_empty(result.get("evidence_gate"))
        if str(evidence_gate.get("status") or "") != "passed":
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="insufficient_evidence",
            )
        raw_results = result.get("results")
        results: list[object] = []
        if isinstance(raw_results, list):
            results = cast(list[object], raw_results)
        try:
            post_ids = select_generation_context_post_ids(
                policy=policy,
                prompt=scene_text,
                results=results,
            )
            reference_metadata = SiteKnowledgeRepository(session).reference_metadata_for_post_ids(
                site_id=site_id, post_ids=post_ids
            )
            pack = build_generation_context_pack(
                policy=policy,
                post_ids=post_ids,
                results=results,
                reference_metadata=reference_metadata,
            )
            reference_block = render_generation_context(pack) if pack is not None else ""
        except Exception:
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="context_assembly_failed",
            )
        if pack is None or not reference_block:
            return self._generation_context_status(
                provider_input,
                mode=mode,
                status="unavailable",
                reason="no_usable_references",
            )
        next_input = dict(provider_input)
        base_input = str(provider_input.get("input") or "")
        scene_marker = "\n\nScene input:\n"
        if scene_marker in base_input:
            next_input["input"] = base_input.replace(
                scene_marker,
                f"\n\n{reference_block}{scene_marker}",
                1,
            )
        else:
            next_input["input"] = f"{reference_block}\n\n{base_input}"
        next_input = self._generation_context_status(
            next_input,
            mode=mode,
            status="applied",
            reason="references_applied",
            reference_count=int(pack["reference_count"]),
            context_chars=int(pack["context_chars"]),
        )
        metadata = dict(self._dict_or_empty(next_input.get("metadata")))
        metadata["site_knowledge_reference"] = "applied"
        metadata["site_knowledge_reference_mode"] = mode
        metadata["site_knowledge_reference_count"] = int(pack["reference_count"])
        next_input["metadata"] = metadata
        return next_input

    def normalize_provider_output(
        self,
        output: dict[str, Any],
        *,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = input_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        task = str(metadata.get("task") or "").strip()
        constraints = {
            str(item).strip()
            for item in metadata.get("task_constraints", [])
            if isinstance(item, str) and str(item).strip()
        }
        output_text = self._extract_provider_output_text(output)
        if task == "alt_text_suggest":
            return self._normalize_alt_text_provider_output(
                output_text=output_text,
            )
        if not output_text:
            return output

        normalized_text = ""
        strips_reasoning_noise = task in {
            "title_generation",
            "excerpt_generation",
            "meta_description",
            "content_summary",
        } and self._has_reasoning_noise(output_text)
        if task == "meta_description":
            normalized_text = self._normalize_meta_description(
                output_text,
                source_text=str(input_payload.get("text") or ""),
            )
        elif task == "content_classification":
            normalized_text = self._normalize_classification_output(
                output_text,
                source_text=str(input_payload.get("text") or ""),
            )
        elif task in (
            "title_generation",
            "excerpt_generation",
            "content_summary",
            "content_rewrite",
        ):
            normalized_text = self._normalize_plain_text_output(
                output_text,
                limit={
                    "content_rewrite": WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS,
                    "title_generation": 80,
                    "excerpt_generation": 180,
                    "content_summary": 220,
                }[task],
                strip_explanation=task in {"title_generation", "content_rewrite"},
                source_text=str(input_payload.get("text") or ""),
                task=task,
            )
        elif "single_value" in constraints:
            normalized_text = self._normalize_plain_text_output(
                output_text,
                limit=320,
                strip_explanation=True,
                source_text=str(input_payload.get("text") or ""),
                task=task,
            )

        if not normalized_text and not strips_reasoning_noise:
            return output

        normalized = dict(output)
        normalized["output_text"] = normalized_text
        normalized["messages"] = [{"role": "assistant", "content": normalized_text}]
        return normalized

    def _normalize_alt_text_provider_output(
        self,
        *,
        output_text: str,
    ) -> dict[str, Any]:
        if not output_text or contains_inline_media_transport(output_text):
            return {}
        normalized_text = self._normalize_plain_text_output(
            output_text,
            limit=240,
            strip_explanation=True,
            task="alt_text_suggest",
        )
        if not normalized_text or contains_inline_media_transport(normalized_text):
            return {}
        return {"output_text": normalized_text}

    def is_empty_text_output(
        self,
        *,
        input_payload: dict[str, Any],
        provider_output: dict[str, Any],
    ) -> bool:
        metadata = input_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        task = str(metadata.get("task") or "").strip()
        constraints = {
            str(item).strip()
            for item in metadata.get("task_constraints", [])
            if isinstance(item, str) and str(item).strip()
        }
        if (
            task
            not in {
                "alt_text_suggest",
                "comment_reply_suggest",
                "content_rewrite",
                "content_summary",
                "excerpt_generation",
                "meta_description",
                "title_generation",
            }
            and "single_value" not in constraints
        ):
            return False
        output_text = self._extract_provider_output_text(provider_output)
        if output_text == "":
            return True
        if task != "title_generation":
            return False
        if self._has_unbalanced_title_quote(output_text):
            return True
        usage = provider_output.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        completion_details = usage.get("completion_tokens_details")
        completion_details = completion_details if isinstance(completion_details, dict) else {}
        reasoning_tokens = self._coerce_int(
            completion_details.get("reasoning_tokens"),
            default=0,
        )
        visible_word_count = len(re.findall(r"\S+", output_text))
        return reasoning_tokens > 0 and visible_word_count <= 3

    def apply_managed_policy(
        self,
        merged_policy: dict[str, object],
        *,
        default_policy: dict[str, object],
        profile_id: str,
    ) -> dict[str, object]:
        if default_policy.get("managed_surface") != "hosted_runtime_profiles":
            return merged_policy
        if (
            default_policy.get("platform_kind") != "wordpress"
            or default_policy.get("connector_id") != "wordpress_ai_connector"
            or default_policy.get("operation_contract_version")
            != WORDPRESS_OPERATION_CONTRACT
        ):
            raise RuntimeExecutionContractError(
                "runtime_profiles.managed_contract_invalid",
                (
                    "hosted runtime profile requires platform_kind=wordpress, "
                    "connector_id=wordpress_ai_connector, and "
                    f"operation_contract_version={WORDPRESS_OPERATION_CONTRACT}"
                ),
            )

        policy = dict(merged_policy)
        spec = resolve_wordpress_ai_connector_profile_spec(profile_id)
        timeout_ms = max(1, self._coerce_int(default_policy.get("timeout_ms"), default=30_000))
        timeout_seconds = max(1, int((timeout_ms + 999) / 1000))
        max_retries = max(0, self._coerce_int(default_policy.get("max_retries"), default=0))
        task_group = str(default_policy.get("task_group") or (spec.group_id if spec else ""))
        routing_intent = str(
            default_policy.get("routing_intent") or (spec.routing_intent if spec else "")
        )
        platform_kind = "wordpress"
        connector_id = "wordpress_ai_connector"
        operation_contract_version = WORDPRESS_OPERATION_CONTRACT
        policy["timeout_ms"] = timeout_ms
        policy["timeout_seconds"] = timeout_seconds
        policy["max_retries"] = max_retries
        policy["retry_max"] = max_retries
        policy["allow_fallback"] = bool(default_policy.get("allow_fallback", True))
        policy["managed_surface"] = "hosted_runtime_profiles"
        policy["platform_kind"] = platform_kind
        policy["connector_id"] = connector_id
        policy["operation_contract_version"] = operation_contract_version
        if task_group:
            policy["task_group"] = task_group
        if routing_intent:
            policy["routing_intent"] = routing_intent

        execution_contract = policy.get("execution_contract")
        if isinstance(execution_contract, dict):
            execution_contract = dict(execution_contract)
            execution_contract["timeout_seconds"] = timeout_seconds
            execution_contract["retry_max"] = max_retries
            execution_contract["managed_surface"] = "hosted_runtime_profiles"
            execution_contract["platform_kind"] = platform_kind
            execution_contract["connector_id"] = connector_id
            execution_contract["operation_contract_version"] = operation_contract_version
            if task_group:
                execution_contract["task_group"] = task_group
            if routing_intent:
                execution_contract["routing_intent"] = routing_intent
            policy["execution_contract"] = execution_contract
        return policy

    def _generation_context_status(
        self,
        provider_input: dict[str, Any],
        *,
        mode: str,
        status: str,
        reason: str,
        reference_count: int = 0,
        context_chars: int = 0,
    ) -> dict[str, Any]:
        next_input = dict(provider_input)
        metadata = dict(self._dict_or_empty(provider_input.get("metadata")))
        metadata.update(
            {
                "generation_context_contract": GENERATION_CONTEXT_CONTRACT,
                "generation_context_status": status,
                "generation_context_mode": mode,
                "generation_context_reason": reason,
                "generation_context_reference_count": max(0, reference_count),
                "generation_context_chars": max(0, context_chars),
            }
        )
        next_input["metadata"] = metadata
        return next_input

    def _build_alt_text_provider_input(
        self,
        *,
        scene_request: dict[str, Any],
        source_artifact: LoadedArtifactInput,
    ) -> dict[str, Any]:
        prompt = cast(str, scene_request["prompt"])
        encoded_image = base64.b64encode(source_artifact.content_bytes).decode("ascii")
        provider_image_url = f"data:{source_artifact.content_type};base64,{encoded_image}"
        context = {
            "task": "alt_text_suggest",
            **{
                field_name: cast(str, scene_request[field_name])
                for field_name in (
                    "locale",
                    "title",
                    "filename",
                    "existing_alt",
                    "existing_caption",
                )
                if field_name in scene_request
            },
            "prompt": prompt,
            "write_posture": "suggestion_only",
        }
        instruction = (
            "Generate concise, accessible WordPress image alt text. "
            "Use the image as the source of truth and use the supplied media context "
            "only to disambiguate. Return only the alt text. Do not mention this "
            "instruction. Do not claim that WordPress metadata was updated."
        )
        context_text = json.dumps(
            {key: value for key, value in context.items() if value},
            ensure_ascii=False,
        )
        responses_content = [
            {"type": "input_text", "text": instruction},
            {"type": "input_text", "text": context_text},
            {"type": "input_image", "image_url": provider_image_url},
        ]
        chat_content = [
            {"type": "text", "text": instruction},
            {"type": "text", "text": context_text},
            {"type": "image_url", "image_url": {"url": provider_image_url}},
        ]

        max_tokens = cast(int, scene_request.get("max_tokens", 48))
        return {
            "input": [{"role": "user", "content": responses_content}],
            "messages": [{"role": "user", "content": chat_content}],
            "text": prompt,
            "max_tokens": max_tokens,
            "max_output_tokens": max_tokens,
            "temperature": 0.0,
            "metadata": {
                "source_surface": "wordpress_ai_connector",
                "task": "alt_text_suggest",
                "suggestion_only": True,
            },
        }

    def _normalize_meta_description(
        self,
        output_text: str,
        *,
        source_text: str = "",
    ) -> str:
        text = self._strip_markdown(self._strip_reasoning_noise(output_text))
        text = re.split(r"\s+#{1,6}\s+", text, maxsplit=1)[0].strip()
        if ":" in text[:64] and len(text.split(":", 1)[1].strip()) >= 40:
            text = text.split(":", 1)[1].strip()
        if self._is_latin_heavy(text) or self._is_boilerplate_output(text):
            cjk_fallback = self._extract_cjk_text(source_text, limit=155)
            if cjk_fallback:
                return cjk_fallback
        if len(text) < 40:
            cjk_fallback = self._extract_cjk_text(source_text, limit=155)
            if cjk_fallback:
                return cjk_fallback
        return self._truncate_text(text, limit=155)

    def _normalize_plain_text_output(
        self,
        output_text: str,
        *,
        limit: int,
        strip_explanation: bool = False,
        source_text: str = "",
        task: str = "",
    ) -> str:
        raw_text = self._strip_reasoning_noise(output_text)
        text = self._extract_task_candidate(raw_text, task=task, limit=limit)
        if not text:
            text = self._strip_markdown(raw_text)
        if strip_explanation:
            text = re.split(
                r"\s+(?:说明|解释|理由|Explanation|Reasoning)\s*[:：]|"
                r"\s+(?:This title|This headline|The title)\b",
                text,
                maxsplit=1,
            )[0].strip()
        if task in {"excerpt_generation", "content_summary"} and (
            self._is_boilerplate_output(text) or self._looks_like_title_bundle(raw_text)
        ):
            cjk_fallback = self._extract_cjk_text(source_text, limit=limit)
            if cjk_fallback:
                return cjk_fallback
        return self._trim_incomplete_tail(self._truncate_text(text, limit=limit))

    def _normalize_classification_output(
        self,
        output_text: str,
        *,
        source_text: str = "",
    ) -> str:
        parsed = self._parse_classification_json(output_text)
        if parsed is None:
            parsed = {
                "suggestions": [
                    {"term": term, "confidence": 0.6, "is_new": True}
                    for term in self._extract_classification_terms(
                        output_text,
                        source_text=source_text,
                    )
                ]
            }
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    def _has_available_terms(self, source_text: str) -> bool:
        match = re.search(
            r"<available-terms>\s*(.*?)\s*</available-terms>",
            source_text,
            flags=re.I | re.S,
        )
        if match is None:
            return False
        return any(item.strip() for item in re.split(r"[,，]", match.group(1)))

    def _parse_classification_json(self, output_text: str) -> dict[str, Any] | None:
        candidates = [output_text.strip()]
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output_text, flags=re.S)
        if fenced:
            candidates.insert(0, fenced.group(1).strip())

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("suggestions"), list):
                return {
                    "suggestions": self._sanitize_classification_suggestions(
                        parsed.get("suggestions")
                    )
                }
        return None

    def _sanitize_classification_suggestions(self, suggestions: Any) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        if not isinstance(suggestions, list):
            return sanitized
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            term = str(suggestion.get("term") or "").strip()
            if not term:
                continue
            confidence = suggestion.get("confidence")
            confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.6
            confidence = max(0.0, min(1.0, confidence))
            sanitized.append(
                {
                    "term": self._truncate_text(term, limit=48),
                    "confidence": confidence,
                    "is_new": bool(suggestion.get("is_new", True)),
                }
            )
            if len(sanitized) >= 5:
                break
        return sanitized

    def _extract_classification_terms(
        self,
        output_text: str,
        *,
        source_text: str = "",
    ) -> list[str]:
        terms: list[str] = []
        for text in (source_text, output_text):
            for match in re.finditer(
                r"\b(?:Npcink|WordPress|Cloud|Addon|API|AI|SEO)"
                r"(?:\s+(?:Npcink|WordPress|Cloud|Addon|API|AI|SEO)){0,3}\b",
                text,
            ):
                term = self._truncate_text(match.group(0), limit=48)
                if 2 <= len(term) <= 48 and term not in terms:
                    terms.append(term)
                if len(terms) >= 3:
                    return terms

        for phrase in (
            "云端运行时",
            "内容分类",
            "建议式输出",
            "通用聊天入口",
            "标题生成",
            "SEO 描述",
        ):
            if phrase in source_text and phrase not in terms:
                terms.append(phrase)
            if len(terms) >= 3:
                return terms

        text = output_text.strip()
        text = re.sub(r"^```(?:json|text|markdown)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"[*_`]+", "", text)
        parts = re.split(r"[\n,，;；、|]+", text)
        for part in parts:
            term = re.sub(r"^\s*[-*\d.)、]+", "", part).strip()
            term = re.sub(r"^(term|tag|category|标签|分类)\s*[:：]\s*", "", term, flags=re.I)
            term = self._truncate_text(term, limit=48)
            if 2 <= len(term) <= 48 and term not in terms:
                terms.append(term)
            if len(terms) >= 3:
                break
        return terms

    def _extract_task_candidate(self, output_text: str, *, task: str, limit: int) -> str:
        if task == "content_rewrite":
            if self._is_boilerplate_output(output_text):
                bold_candidate = self._extract_bold_candidate(output_text)
                if bold_candidate:
                    return self._truncate_text(bold_candidate, limit=limit)
            alternative_candidate = self._extract_rewrite_alternative_candidate(output_text)
            if alternative_candidate:
                return self._truncate_text(alternative_candidate, limit=limit)
            text = self._strip_markdown(output_text)
            text = re.sub(
                r"^(?:rewrite|rewritten|rephrased|改写(?:结果|版本)?|"
                r"建议改写(?:为|成))\s*[:：]\s*",
                "",
                text,
                flags=re.I,
            )
            if text and not self._is_boilerplate_output(text):
                return self._truncate_text(text, limit=limit)
        if task == "title_generation":
            heading_candidate = self._extract_title_heading(output_text)
            if heading_candidate:
                return self._truncate_text(heading_candidate, limit=limit)
            list_candidate = self._extract_first_list_item(output_text)
            if list_candidate:
                return self._truncate_text(list_candidate, limit=limit)
            text = self._strip_markdown(output_text)
            text = re.split(
                r"\s+(?:摘要|summary)\s*[:：]|\s+---\s+",
                text,
                maxsplit=1,
                flags=re.I,
            )[0].strip()
            if not self._is_boilerplate_output(text):
                return self._truncate_text(text, limit=limit)
        return ""

    def _extract_title_heading(self, output_text: str) -> str:
        for line in output_text.splitlines():
            match = re.match(r"\s*#{1,6}\s+(.+?)\s*$", line)
            if match is None:
                continue
            candidate = self._strip_markdown(match.group(1))
            if self._is_boilerplate_output(candidate):
                continue
            if 4 <= len(candidate) <= 120:
                return candidate
        return ""

    def _extract_bold_candidate(self, output_text: str) -> str:
        for match in re.finditer(
            r"(?m)^\s*\*\*(.{4,260}?)\*\*\s*$",
            output_text,
        ):
            candidate = self._strip_markdown(match.group(1))
            if re.search(r"(?:版|version|option)\s*[:：]?$", candidate, flags=re.I):
                continue
            if len(candidate) >= 8:
                return candidate
        return ""

    def _extract_rewrite_alternative_candidate(self, output_text: str) -> str:
        """Extract one candidate only from a complete, high-confidence bundle."""
        text = self._strip_markdown(output_text)
        match = re.fullmatch(
            r"(?P<first>.+?[.!?])\s+OR\s+"
            r"(?P<second>.+?[.!?])\s+"
            r"Both(?:\s+rephrasings)?\s+preserve\s+(?:the\s+)?"
            r"(?:core|original|intended)\s+meaning\b.+",
            text,
            flags=re.I | re.S,
        )
        if match is None:
            return ""
        candidate = match.group("first").strip()
        if len(candidate) < 8 or self._is_boilerplate_output(candidate):
            return ""
        return candidate

    def _extract_first_list_item(self, output_text: str) -> str:
        for line in output_text.splitlines():
            match = re.match(r"\s*(?:[-*]|\d+[.)、])\s*(.+?)\s*$", line)
            if match is None:
                continue
            candidate = self._strip_markdown(match.group(1))
            candidate = re.sub(r"^[\"'“”‘’《》]+|[\"'“”‘’《》]+$", "", candidate).strip()
            if 4 <= len(candidate) <= 120:
                return candidate
        match = re.search(
            r"(?:^|\s)\d+[.)、]\s*(.+?)(?=\s+\d+[.)、]\s+|$)",
            output_text,
        )
        if match is not None:
            candidate = self._strip_markdown(match.group(1))
            candidate = re.sub(r"^[\"'“”‘’《》]+|[\"'“”‘’《》]+$", "", candidate).strip()
            if 4 <= len(candidate) <= 120:
                return candidate
        return ""

    @staticmethod
    def _extract_provider_output_text(output: dict[str, Any]) -> str:
        for key in ("output_text", "text", "content"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                text = choice.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
        return ""

    @staticmethod
    def _has_unbalanced_title_quote(output_text: str) -> bool:
        text = output_text.strip()
        if not text:
            return False
        quote_pairs = {
            '"': '"',
            "'": "'",
            "“": "”",
            "‘": "’",
            "「": "」",
            "『": "』",
            "《": "》",
        }
        closing = quote_pairs.get(text[0])
        return bool(closing and not text.endswith(closing))

    @staticmethod
    def _strip_markdown(output_text: str) -> str:
        text = output_text.strip()
        text = re.sub(r"^```(?:json|text|markdown)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
        text = re.sub(r"[*_`]+", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _is_boilerplate_output(text: str) -> bool:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in (
                "以下是基于",
                "下面是",
                "以下是",
                "如果你愿意",
                "我还可以",
                "here are",
                "based on your",
                "i can also",
                "title suggestions",
                "标题建议",
                "多个版本",
            )
        )

    @staticmethod
    def _looks_like_title_bundle(text: str) -> bool:
        return bool(
            re.search(r"(?:标题建议|title suggestions)", text, flags=re.I)
            or re.search(r"(?m)^\s*\d+[.)、]\s*.{4,80}$", text)
            and len(re.findall(r"(?m)^\s*\d+[.)、]\s+", text)) >= 2
            or re.match(r"^\s*《[^》]{4,80}》\s*(?:#{1,6}\s*)?", text)
        )

    @staticmethod
    def _strip_reasoning_noise(output_text: str) -> str:
        text = output_text.strip()
        text = re.sub(r"(?is)<think\b[^>]*>.*?</think>", " ", text)
        text = re.sub(r"(?is)^\s*<think\b[^>]*>.*?(?:\r?\n\s*\r?\n|$)", "", text)
        text = re.sub(
            r"(?is)^\s*(?:reasoning|explanation|analysis)\s*[:：].*?"
            r"(?:\r?\n\s*\r?\n|$)",
            "",
            text,
        )
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _has_reasoning_noise(output_text: str) -> bool:
        return bool(
            re.search(
                r"(?is)<think\b|^\s*(?:reasoning|explanation|analysis)\s*[:：]",
                output_text,
            )
        )

    @staticmethod
    def _is_latin_heavy(text: str) -> bool:
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        return latin_count > max(24, cjk_count * 2)

    def _extract_cjk_text(self, source_text: str, *, limit: int) -> str:
        fragments = re.findall(
            r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9，。！？、：；（）《》“”\"'\s-]{16,}",
            source_text,
        )
        if not fragments:
            return ""
        text = max((fragment.strip() for fragment in fragments), key=len)
        text = re.sub(r"\s+", " ", text).strip()
        return self._truncate_text(text, limit=limit)

    @staticmethod
    def _trim_incomplete_tail(text: str) -> str:
        return re.sub(r"\s+\d+[.)、]?$", "", text).strip()

    @staticmethod
    def _truncate_text(text: str, *, limit: int) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        candidate = text[:limit].rstrip()
        punctuation_index = max(
            candidate.rfind("。"),
            candidate.rfind("！"),
            candidate.rfind("？"),
            candidate.rfind("."),
            candidate.rfind("!"),
            candidate.rfind("?"),
        )
        if punctuation_index >= 80:
            return candidate[: punctuation_index + 1].strip()
        return candidate[: max(0, limit - 3)].rstrip("，,；;：:、 ") + "..."

    @staticmethod
    def _coerce_int(value: object | None, *, default: int) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _dict_or_empty(value: object | None) -> dict[str, object]:
        return value if isinstance(value, dict) else {}
