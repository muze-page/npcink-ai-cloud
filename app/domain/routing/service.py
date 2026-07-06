from __future__ import annotations

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session
from app.domain.provider_connections.model_allowlist import build_provider_model_allowlist
from app.domain.routing.errors import (
    RoutingExecutionKindMismatchError,
    RoutingNoCandidatesError,
    RoutingProfileNotFoundError,
)
from app.domain.routing.models import RoutingCandidate, RoutingResolution


class RoutingService:
    def __init__(
        self,
        database_url: str,
        *,
        settings: Settings | None = None,
        execution_provider_ids: set[str] | None = None,
    ) -> None:
        self.database_url = database_url
        self.settings = settings
        self.execution_provider_ids = execution_provider_ids or set()

    def resolve(
        self,
        *,
        profile_id: str,
        execution_kind: str,
    ) -> RoutingResolution:
        provider_model_allowlist = build_provider_model_allowlist(
            self.database_url,
            settings=self.settings,
            execution_provider_ids=self.execution_provider_ids,
        )
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            profile = repository.get_routing_profile(profile_id)
            if profile is None:
                raise RoutingProfileNotFoundError(profile_id)

            if profile.execution_kind != execution_kind:
                raise RoutingExecutionKindMismatchError(
                    profile_id,
                    profile.execution_kind,
                    execution_kind,
                )

            binding = repository.get_routing_binding(profile_id)
            if binding is None:
                raise RoutingNoCandidatesError(profile_id)

            instances = repository.list_instances_by_ids(binding.candidate_instance_ids)
            models = repository.list_models_by_ids([instance.model_id for instance in instances])
            models_by_id = {model.model_id: model for model in models}

        candidates = [
            RoutingCandidate(
                provider_id=instance.provider_id,
                model_id=instance.model_id,
                instance_id=instance.instance_id,
                endpoint_variant=instance.endpoint_variant,
                region=instance.region,
                weight=instance.weight,
                health_status=instance.health_status,
                price_input=models_by_id[instance.model_id].price_input,
                price_output=models_by_id[instance.model_id].price_output,
                capability_tags=instance.capability_tags,
            )
            for instance in instances
            if instance.health_status != "unhealthy"
            and instance.model_id in models_by_id
            and models_by_id[instance.model_id].status == "available"
            and not models_by_id[instance.model_id].is_deprecated
            and provider_model_allowlist.allows(
                provider_id=instance.provider_id,
                model_id=instance.model_id,
            )
            and self._provider_is_executable(instance.provider_id)
        ]

        if not candidates:
            raise RoutingNoCandidatesError(profile_id)

        return RoutingResolution(
            profile_id=profile.profile_id,
            execution_kind=profile.execution_kind,
            revision=binding.revision,
            default_policy=profile.default_policy_json or {},
            selection_policy=binding.selection_policy_json or {},
            candidates=candidates,
        )

    def _provider_is_executable(self, provider_id: str) -> bool:
        if not self.execution_provider_ids:
            return True
        return provider_id in self.execution_provider_ids
