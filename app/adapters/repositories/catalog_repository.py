from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.providers.base import ProviderCatalogSnapshot
from app.core.models import (
    CatalogInstance,
    CatalogModel,
    CatalogProvider,
    CatalogRevision,
    HealthSnapshot,
    ProviderCallRecord,
    RoutingBinding,
    RoutingProfile,
    RunRecord,
)


class CatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_latest_revision(self) -> CatalogRevision | None:
        statement = select(CatalogRevision).order_by(
            CatalogRevision.created_at.desc(),
            CatalogRevision.id.desc(),
        )
        return self.session.scalar(statement)

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        feature: str | None = None,
        status: str | None = None,
        search: str | None = None,
        fallback_candidate: bool | None = None,
        deprecated_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogModel], int]:
        statement = select(CatalogModel).order_by(
            CatalogModel.provider_id.asc(),
            CatalogModel.model_id.asc(),
        )

        if provider_id:
            statement = statement.where(CatalogModel.provider_id == provider_id)
        if feature:
            statement = statement.where(CatalogModel.feature == feature)
        if status:
            statement = statement.where(CatalogModel.status == status)
        if search:
            search_term = f"%{search.lower()}%"
            statement = statement.where(func.lower(CatalogModel.model_id).like(search_term))
        if fallback_candidate is not None:
            statement = statement.where(CatalogModel.fallback_candidate == fallback_candidate)
        if deprecated_only:
            statement = statement.where(CatalogModel.is_deprecated.is_(True))

        count_statement = select(func.count()).select_from(statement.subquery())
        total = int(self.session.scalar(count_statement) or 0)

        paged_statement = statement.limit(limit).offset(offset)
        items = list(self.session.scalars(paged_statement))
        return items, total

    def list_all_models(self) -> list[CatalogModel]:
        statement = select(CatalogModel).order_by(
            CatalogModel.provider_id.asc(),
            CatalogModel.model_id.asc(),
        )
        return list(self.session.scalars(statement))

    def list_providers_by_ids(self, provider_ids: list[str]) -> list[CatalogProvider]:
        if not provider_ids:
            return []

        statement = select(CatalogProvider).where(CatalogProvider.provider_id.in_(provider_ids))
        providers_by_id = {
            provider.provider_id: provider for provider in self.session.scalars(statement)
        }
        return [
            providers_by_id[provider_id]
            for provider_id in provider_ids
            if provider_id in providers_by_id
        ]

    def get_model(self, model_id: str) -> CatalogModel | None:
        return self.session.get(CatalogModel, model_id)

    def list_instances_for_model(self, model_id: str) -> list[CatalogInstance]:
        statement = (
            select(CatalogInstance)
            .where(CatalogInstance.model_id == model_id)
            .order_by(CatalogInstance.instance_id.asc())
        )
        return list(self.session.scalars(statement))

    def list_instances_for_provider(
        self,
        provider_id: str | None = None,
    ) -> list[CatalogInstance]:
        statement = select(CatalogInstance).order_by(
            CatalogInstance.provider_id.asc(),
            CatalogInstance.instance_id.asc(),
        )
        if provider_id:
            statement = statement.where(CatalogInstance.provider_id == provider_id)
        return list(self.session.scalars(statement))

    def list_instances_by_ids(self, instance_ids: list[str]) -> list[CatalogInstance]:
        if not instance_ids:
            return []

        statement = select(CatalogInstance).where(CatalogInstance.instance_id.in_(instance_ids))
        instances_by_id = {
            instance.instance_id: instance for instance in self.session.scalars(statement)
        }
        return [
            instances_by_id[instance_id]
            for instance_id in instance_ids
            if instance_id in instances_by_id
        ]

    def list_models_by_ids(self, model_ids: list[str]) -> list[CatalogModel]:
        if not model_ids:
            return []

        statement = select(CatalogModel).where(CatalogModel.model_id.in_(model_ids))
        models_by_id = {model.model_id: model for model in self.session.scalars(statement)}
        return [models_by_id[model_id] for model_id in model_ids if model_id in models_by_id]

    def list_provider_calls_for_instances(
        self,
        instance_ids: list[str],
        site_id: str | None = None,
    ) -> list[ProviderCallRecord]:
        if not instance_ids:
            return []

        statement = select(ProviderCallRecord).where(
            ProviderCallRecord.instance_id.in_(instance_ids)
        )
        if site_id:
            statement = statement.join(RunRecord, RunRecord.run_id == ProviderCallRecord.run_id)
            statement = statement.where(RunRecord.site_id == site_id)
        statement = statement.order_by(
            ProviderCallRecord.created_at.asc(),
            ProviderCallRecord.id.asc(),
        )
        return list(self.session.scalars(statement))

    def get_routing_profile(self, profile_id: str) -> RoutingProfile | None:
        return self.session.get(RoutingProfile, profile_id)

    def get_routing_binding(self, profile_id: str) -> RoutingBinding | None:
        return self.session.get(RoutingBinding, profile_id)

    def upsert_provider_snapshot(self, snapshot: ProviderCatalogSnapshot, revision: str) -> None:
        incoming_model_ids = [model_seed.model_id for model_seed in snapshot.models]
        incoming_instance_ids = [
            instance_seed.instance_id
            for model_seed in snapshot.models
            for instance_seed in model_seed.instances
        ]

        self.session.merge(
            CatalogProvider(
                provider_id=snapshot.provider_id,
                display_name=snapshot.display_name,
                adapter_type=snapshot.adapter_type,
                status="active",
                last_refreshed_at=datetime.now(UTC),
                metadata_json={"revision": revision},
            )
        )
        self.session.flush()

        stale_instances_statement = select(CatalogInstance).where(
            CatalogInstance.provider_id == snapshot.provider_id
        )
        if incoming_instance_ids:
            stale_instances_statement = stale_instances_statement.where(
                CatalogInstance.instance_id.not_in(incoming_instance_ids)
            )
        stale_instances = list(self.session.scalars(stale_instances_statement))
        for instance in stale_instances:
            self.session.delete(instance)

        stale_models_statement = select(CatalogModel).where(
            CatalogModel.provider_id == snapshot.provider_id
        )
        if incoming_model_ids:
            stale_models_statement = stale_models_statement.where(
                CatalogModel.model_id.not_in(incoming_model_ids)
            )
        stale_models = list(self.session.scalars(stale_models_statement))
        for model in stale_models:
            self.session.delete(model)

        for model_seed in snapshot.models:
            self.session.merge(
                CatalogModel(
                    model_id=model_seed.model_id,
                    provider_id=snapshot.provider_id,
                    family=model_seed.family,
                    feature=model_seed.feature,
                    status=model_seed.status,
                    context_window=model_seed.context_window,
                    price_input=model_seed.price_input,
                    price_output=model_seed.price_output,
                    is_deprecated=model_seed.is_deprecated,
                    fallback_candidate=model_seed.fallback_candidate,
                    revision=revision,
                    raw_json=model_seed.raw_json,
                )
            )
        self.session.flush()

        for model_seed in snapshot.models:
            for instance_seed in model_seed.instances:
                self.session.merge(
                    CatalogInstance(
                        instance_id=instance_seed.instance_id,
                        model_id=model_seed.model_id,
                        provider_id=snapshot.provider_id,
                        endpoint_variant=instance_seed.endpoint_variant,
                        region=instance_seed.region,
                        capability_tags=instance_seed.capability_tags,
                        health_status=instance_seed.health_status,
                        is_default=instance_seed.is_default,
                        weight=instance_seed.weight,
                    )
                )

    def create_revision(
        self,
        revision: str,
        provider_id: str | None,
        source: str,
        notes: str | None = None,
    ) -> None:
        self.session.add(
            CatalogRevision(
                revision=revision,
                provider_id=provider_id,
                source=source,
                notes=notes,
            )
        )

    def upsert_routing_profile(
        self,
        *,
        profile_id: str,
        execution_kind: str,
        default_policy_json: dict[str, object] | None = None,
    ) -> None:
        self.session.merge(
            RoutingProfile(
                profile_id=profile_id,
                execution_kind=execution_kind,
                default_policy_json=default_policy_json,
            )
        )

    def upsert_routing_binding(
        self,
        *,
        profile_id: str,
        candidate_instance_ids: list[str],
        selection_policy_json: dict[str, object] | None,
        revision: str,
    ) -> None:
        self.session.merge(
            RoutingBinding(
                profile_id=profile_id,
                candidate_instance_ids=candidate_instance_ids,
                selection_policy_json=selection_policy_json,
                revision=revision,
            )
        )

    def record_health_snapshot(
        self,
        provider_id: str,
        instance_id: str | None,
        status: str,
        reason: str,
    ) -> None:
        self.session.add(
            HealthSnapshot(
                provider_id=provider_id,
                instance_id=instance_id,
                status=status,
                reason=reason,
            )
        )

    def update_instance_health_status(
        self,
        instance_id: str,
        health_status: str,
    ) -> None:
        instance = self.session.get(CatalogInstance, instance_id)
        if instance is None:
            return
        instance.health_status = health_status
        self.session.flush()
