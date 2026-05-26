from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.providers.base import ProviderCatalogSnapshot
from app.core.models import (
    CatalogInstance,
    CatalogModelAnnotation,
    CatalogModel,
    CatalogProvider,
    ProviderConnection,
    CatalogRevision,
    HealthSnapshot,
    ProviderCallRecord,
    RecognitionModelAnnotation,
    RecognitionSnapshotPublication,
    RecognitionSourceRun,
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

    def list_model_annotations(
        self,
        model_ids: list[str] | None = None,
    ) -> list[CatalogModelAnnotation]:
        statement = select(CatalogModelAnnotation).order_by(
            CatalogModelAnnotation.provider_id.asc(),
            CatalogModelAnnotation.model_id.asc(),
        )
        if model_ids is not None:
            if not model_ids:
                return []
            statement = statement.where(CatalogModelAnnotation.model_id.in_(model_ids))
        return list(self.session.scalars(statement))

    def get_model_annotation(self, model_id: str) -> CatalogModelAnnotation | None:
        return self.session.get(CatalogModelAnnotation, model_id)

    def get_model(self, model_id: str) -> CatalogModel | None:
        return self.session.get(CatalogModel, model_id)

    def list_provider_connections(self) -> list[ProviderConnection]:
        statement = select(ProviderConnection).order_by(
            ProviderConnection.provider_type.asc(),
            ProviderConnection.display_name.asc(),
            ProviderConnection.connection_id.asc(),
        )
        return list(self.session.scalars(statement))

    def list_enabled_provider_connections(
        self,
        *,
        source_roles: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[ProviderConnection]:
        statement = (
            select(ProviderConnection)
            .where(ProviderConnection.enabled.is_(True))
            .order_by(
                ProviderConnection.provider_type.asc(),
                ProviderConnection.display_name.asc(),
                ProviderConnection.connection_id.asc(),
            )
        )
        if source_roles is not None:
            normalized_roles = [
                str(role).strip().lower()
                for role in source_roles
                if str(role).strip()
            ]
            if not normalized_roles:
                return []
            statement = statement.where(ProviderConnection.source_role.in_(normalized_roles))
        return list(self.session.scalars(statement))

    def get_provider_connection(self, connection_id: str) -> ProviderConnection | None:
        return self.session.get(ProviderConnection, connection_id)

    def upsert_provider_connection(
        self,
        *,
        connection_id: str,
        provider_type: str,
        source_role: str,
        display_name: str,
        enabled: bool,
        base_url: str,
        config_json: dict[str, object] | None,
        secret_ciphertext: str | None,
        status: str,
        metadata_json: dict[str, object] | None = None,
    ) -> ProviderConnection:
        existing = self.get_provider_connection(connection_id)
        connection = ProviderConnection(
            connection_id=connection_id,
            provider_type=provider_type,
            source_role=source_role,
            display_name=display_name,
            enabled=enabled,
            base_url=base_url,
            config_json=config_json,
            secret_ciphertext=(
                secret_ciphertext
                if secret_ciphertext is not None
                else (existing.secret_ciphertext if existing is not None else None)
            ),
            status=status,
            last_tested_at=existing.last_tested_at if existing is not None else None,
            last_sync_at=existing.last_sync_at if existing is not None else None,
            last_error_code=existing.last_error_code if existing is not None else None,
            last_error_message=existing.last_error_message if existing is not None else None,
            metadata_json=metadata_json,
        )
        return self.session.merge(connection)

    def update_provider_connection_status(
        self,
        *,
        connection_id: str,
        status: str,
        last_tested_at: datetime | None = None,
        last_sync_at: datetime | None = None,
        last_error_code: str | None = None,
        last_error_message: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> ProviderConnection | None:
        connection = self.get_provider_connection(connection_id)
        if connection is None:
            return None
        connection.status = status
        if last_tested_at is not None:
            connection.last_tested_at = last_tested_at
        if last_sync_at is not None:
            connection.last_sync_at = last_sync_at
        connection.last_error_code = last_error_code
        connection.last_error_message = last_error_message
        if metadata_json is not None:
            connection.metadata_json = metadata_json
        return connection

    def upsert_model_annotation(
        self,
        *,
        model_id: str,
        provider_id: str,
        recommended: bool,
        cost_tier: str | None,
        visibility: str,
        badges_json: list[str],
        operator_notes: str | None,
        metadata_json: dict[str, object] | None = None,
    ) -> CatalogModelAnnotation:
        annotation = CatalogModelAnnotation(
            model_id=model_id,
            provider_id=provider_id,
            recommended=recommended,
            cost_tier=cost_tier,
            visibility=visibility,
            badges_json=badges_json,
            operator_notes=operator_notes,
            metadata_json=metadata_json,
        )
        return self.session.merge(annotation)

    def list_recognition_annotations(
        self,
        provider_model_keys: list[tuple[str, str]] | None = None,
    ) -> list[RecognitionModelAnnotation]:
        statement = select(RecognitionModelAnnotation).order_by(
            RecognitionModelAnnotation.provider_id.asc(),
            RecognitionModelAnnotation.model_id.asc(),
        )
        if provider_model_keys is not None:
            if not provider_model_keys:
                return []
            provider_ids = [item[0] for item in provider_model_keys]
            model_ids = [item[1] for item in provider_model_keys]
            statement = statement.where(
                RecognitionModelAnnotation.provider_id.in_(provider_ids),
                RecognitionModelAnnotation.model_id.in_(model_ids),
            )
        annotations = list(self.session.scalars(statement))
        if provider_model_keys is None:
            return annotations
        wanted = set(provider_model_keys)
        return [
            item
            for item in annotations
            if (item.provider_id, item.model_id) in wanted
        ]

    def get_recognition_annotation(
        self,
        *,
        provider_id: str,
        model_id: str,
    ) -> RecognitionModelAnnotation | None:
        statement = select(RecognitionModelAnnotation).where(
            RecognitionModelAnnotation.provider_id == provider_id,
            RecognitionModelAnnotation.model_id == model_id,
        )
        return self.session.scalar(statement)

    def upsert_recognition_annotation(
        self,
        *,
        provider_id: str,
        model_id: str,
        review_status: str,
        manual_tags_json: list[str],
        operator_notes: str | None,
        metadata_json: dict[str, object] | None = None,
    ) -> RecognitionModelAnnotation:
        existing = self.get_recognition_annotation(
            provider_id=provider_id,
            model_id=model_id,
        )
        annotation = RecognitionModelAnnotation(
            id=existing.id if existing is not None else None,
            provider_id=provider_id,
            model_id=model_id,
            review_status=review_status,
            manual_tags_json=manual_tags_json,
            operator_notes=operator_notes,
            metadata_json=metadata_json,
        )
        return self.session.merge(annotation)

    def upsert_recognition_source_run(
        self,
        *,
        run_id: str,
        source_name: str,
        snapshot_generated_at: datetime | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        status: str,
        duration_ms: int,
        records_fetched: int,
        records_accepted: int,
        error_message: str | None,
        metadata_json: dict[str, object] | None = None,
    ) -> RecognitionSourceRun:
        existing = self.get_recognition_source_run(run_id)
        source_run = RecognitionSourceRun(
            id=existing.id if existing is not None else None,
            run_id=run_id,
            source_name=source_name,
            snapshot_generated_at=snapshot_generated_at,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            duration_ms=max(0, int(duration_ms)),
            records_fetched=max(0, int(records_fetched)),
            records_accepted=max(0, int(records_accepted)),
            error_message=error_message,
            metadata_json=metadata_json,
        )
        return self.session.merge(source_run)

    def get_recognition_source_run(self, run_id: str) -> RecognitionSourceRun | None:
        statement = select(RecognitionSourceRun).where(
            RecognitionSourceRun.run_id == run_id
        )
        return self.session.scalar(statement)

    def list_recent_recognition_source_runs(
        self,
        *,
        limit: int = 20,
    ) -> list[RecognitionSourceRun]:
        statement = (
            select(RecognitionSourceRun)
            .order_by(
                RecognitionSourceRun.snapshot_generated_at.desc(),
                RecognitionSourceRun.id.desc(),
            )
            .limit(max(1, int(limit)))
        )
        return list(self.session.scalars(statement))

    def upsert_recognition_snapshot_publication(
        self,
        *,
        revision: str,
        checksum: str,
        generated_at: datetime,
        records_total: int,
        source_keys_json: list[str],
        source_run_ids_json: list[str],
        record_keys_json: list[str],
        metadata_json: dict[str, object] | None = None,
    ) -> RecognitionSnapshotPublication:
        existing = self.get_recognition_snapshot_publication_by_revision(revision)
        publication = RecognitionSnapshotPublication(
            id=existing.id if existing is not None else None,
            revision=revision,
            checksum=checksum,
            generated_at=generated_at,
            records_total=max(0, int(records_total)),
            source_keys_json=source_keys_json,
            source_run_ids_json=source_run_ids_json,
            record_keys_json=record_keys_json,
            metadata_json=metadata_json,
        )
        return self.session.merge(publication)

    def get_recognition_snapshot_publication_by_revision(
        self,
        revision: str,
    ) -> RecognitionSnapshotPublication | None:
        statement = select(RecognitionSnapshotPublication).where(
            RecognitionSnapshotPublication.revision == revision
        )
        return self.session.scalar(statement)

    def list_recent_recognition_snapshot_publications(
        self,
        *,
        limit: int = 2,
    ) -> list[RecognitionSnapshotPublication]:
        statement = (
            select(RecognitionSnapshotPublication)
            .order_by(
                RecognitionSnapshotPublication.generated_at.desc(),
                RecognitionSnapshotPublication.id.desc(),
            )
            .limit(max(1, int(limit)))
        )
        return list(self.session.scalars(statement))

    def list_instances_for_model(self, model_id: str) -> list[CatalogInstance]:
        statement = select(CatalogInstance).where(CatalogInstance.model_id == model_id).order_by(
            CatalogInstance.instance_id.asc()
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
            annotation = self.get_model_annotation(model.model_id)
            if annotation is not None:
                self.session.delete(annotation)
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
