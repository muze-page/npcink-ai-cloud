from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, Integer, Select, and_, case, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.core.models import (
    CatalogInstance,
    CatalogModel,
    HealthSnapshot,
    ProviderCallRecord,
    RoutingBinding,
    RoutingProfile,
    RunRecord,
    Site,
    UsageRollup,
)


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _normalize_site_ids(self, site_ids: list[str] | None) -> list[str] | None:
        if site_ids is None:
            return None
        return sorted({str(site_id).strip() for site_id in site_ids if str(site_id).strip()})

    def get_instance(self, instance_id: str) -> CatalogInstance | None:
        return self.session.get(CatalogInstance, instance_id)

    def get_model(self, model_id: str) -> CatalogModel | None:
        return self.session.get(CatalogModel, model_id)

    def list_instances(self) -> list[CatalogInstance]:
        statement = select(CatalogInstance).order_by(
            CatalogInstance.provider_id.asc(),
            CatalogInstance.instance_id.asc(),
        )
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

    def get_profile(self, profile_id: str) -> RoutingProfile | None:
        return self.session.get(RoutingProfile, profile_id)

    def list_profiles(self) -> list[RoutingProfile]:
        statement = select(RoutingProfile).order_by(RoutingProfile.profile_id.asc())
        return list(self.session.scalars(statement))

    def get_routing_binding(self, profile_id: str) -> RoutingBinding | None:
        return self.session.get(RoutingBinding, profile_id)

    def list_site_ids(self) -> list[str]:
        statement = select(Site.site_id).order_by(Site.site_id.asc())
        return [site_id for site_id in self.session.scalars(statement)]

    def count_sites(self) -> int:
        statement = select(func.count()).select_from(Site)
        return int(self.session.scalar(statement) or 0)

    def count_profiles(self) -> int:
        statement = select(func.count()).select_from(RoutingProfile)
        return int(self.session.scalar(statement) or 0)

    def list_runs(
        self,
        site_id: str | None = None,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[RunRecord]:
        statement = select(RunRecord)
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        statement = self._apply_run_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        statement = statement.order_by(RunRecord.started_at.asc(), RunRecord.run_id.asc())
        return list(self.session.scalars(statement))

    def list_runs_for_profile(
        self,
        profile_id: str,
        site_id: str | None = None,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[RunRecord]:
        statement = select(RunRecord).where(RunRecord.profile_id == profile_id)
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        statement = self._apply_run_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        statement = statement.order_by(RunRecord.started_at.asc(), RunRecord.run_id.asc())
        return list(self.session.scalars(statement))

    def list_provider_calls(
        self,
        site_id: str | None = None,
        *,
        site_ids: list[str] | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ProviderCallRecord]:
        normalized_site_ids = self._normalize_site_ids(site_ids)
        if normalized_site_ids is not None and not normalized_site_ids:
            return []
        statement = select(ProviderCallRecord)
        if site_id or normalized_site_ids is not None:
            statement = statement.join(RunRecord, RunRecord.run_id == ProviderCallRecord.run_id)
        if normalized_site_ids is not None:
            statement = statement.where(RunRecord.site_id.in_(normalized_site_ids))
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        statement = self._apply_provider_call_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        statement = statement.order_by(
            ProviderCallRecord.created_at.asc(),
            ProviderCallRecord.id.asc(),
        )
        return list(self.session.scalars(statement))

    def list_provider_calls_for_instance(
        self,
        instance_id: str,
        site_id: str | None = None,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ProviderCallRecord]:
        statement = select(ProviderCallRecord).where(ProviderCallRecord.instance_id == instance_id)
        if site_id:
            statement = statement.join(RunRecord, RunRecord.run_id == ProviderCallRecord.run_id)
            statement = statement.where(RunRecord.site_id == site_id)
        statement = self._apply_provider_call_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        statement = statement.order_by(
            ProviderCallRecord.created_at.asc(),
            ProviderCallRecord.id.asc(),
        )
        return list(self.session.scalars(statement))

    def list_provider_calls_for_instances(
        self,
        instance_ids: list[str],
        site_id: str | None = None,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ProviderCallRecord]:
        if not instance_ids:
            return []

        statement = select(ProviderCallRecord).where(
            ProviderCallRecord.instance_id.in_(instance_ids)
        )
        if site_id:
            statement = statement.join(RunRecord, RunRecord.run_id == ProviderCallRecord.run_id)
            statement = statement.where(RunRecord.site_id == site_id)
        statement = self._apply_provider_call_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        statement = statement.order_by(
            ProviderCallRecord.created_at.asc(),
            ProviderCallRecord.id.asc(),
        )
        return list(self.session.scalars(statement))

    def aggregate_provider_calls_window(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
        instance_id: str | None = None,
        instance_ids: list[str] | None = None,
        constrain_run_started: bool = False,
    ) -> dict[str, object]:
        normalized_site_ids = self._normalize_site_ids(site_ids)
        if normalized_site_ids is not None and not normalized_site_ids:
            return self._empty_provider_call_metrics()
        joins_run_record = bool(site_id) or normalized_site_ids is not None or constrain_run_started
        statement = select(
            func.count(ProviderCallRecord.id),
            func.sum(case((ProviderCallRecord.error_code.is_(None), 1), else_=0)),
            func.sum(case((ProviderCallRecord.fallback_used.is_(True), 1), else_=0)),
            func.avg(ProviderCallRecord.latency_ms),
            func.sum(ProviderCallRecord.tokens_in),
            func.sum(ProviderCallRecord.tokens_out),
            func.sum(ProviderCallRecord.cost),
            func.max(ProviderCallRecord.created_at),
        )
        if joins_run_record:
            statement = statement.select_from(ProviderCallRecord).join(
                RunRecord,
                RunRecord.run_id == ProviderCallRecord.run_id,
            )
        if normalized_site_ids is not None:
            statement = statement.where(RunRecord.site_id.in_(normalized_site_ids))
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if instance_id:
            statement = statement.where(ProviderCallRecord.instance_id == instance_id)
        if instance_ids is not None:
            if not instance_ids:
                return self._empty_provider_call_metrics()
            statement = statement.where(ProviderCallRecord.instance_id.in_(instance_ids))
        if constrain_run_started:
            statement = statement.where(
                RunRecord.started_at.is_not(None),
                RunRecord.started_at >= start_at,
                RunRecord.started_at <= end_at,
            )
        statement = self._apply_provider_call_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        (
            calls_total,
            success_total,
            fallback_total,
            avg_latency_ms,
            tokens_in_total,
            tokens_out_total,
            cost_total,
            last_seen_at,
        ) = self.session.execute(statement).one()
        return {
            "calls_total": int(calls_total or 0),
            "success_total": int(success_total or 0),
            "fallback_total": int(fallback_total or 0),
            "avg_latency_ms": int(round(float(avg_latency_ms or 0))),
            "tokens_in_total": int(tokens_in_total or 0),
            "tokens_out_total": int(tokens_out_total or 0),
            "cost_total": round(float(cost_total or 0.0), 6),
            "last_seen_at": last_seen_at,
        }

    def list_provider_call_latency_values_window(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
        instance_id: str | None = None,
        instance_ids: list[str] | None = None,
        constrain_run_started: bool = False,
    ) -> list[int]:
        normalized_site_ids = self._normalize_site_ids(site_ids)
        if normalized_site_ids is not None and not normalized_site_ids:
            return []
        joins_run_record = bool(site_id) or normalized_site_ids is not None or constrain_run_started
        statement = select(ProviderCallRecord.latency_ms).where(
            ProviderCallRecord.latency_ms.is_not(None)
        )
        if joins_run_record:
            statement = statement.select_from(ProviderCallRecord).join(
                RunRecord,
                RunRecord.run_id == ProviderCallRecord.run_id,
            )
        if normalized_site_ids is not None:
            statement = statement.where(RunRecord.site_id.in_(normalized_site_ids))
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if instance_id:
            statement = statement.where(ProviderCallRecord.instance_id == instance_id)
        if instance_ids is not None:
            if not instance_ids:
                return []
            statement = statement.where(ProviderCallRecord.instance_id.in_(instance_ids))
        if constrain_run_started:
            statement = statement.where(
                RunRecord.started_at.is_not(None),
                RunRecord.started_at >= start_at,
                RunRecord.started_at <= end_at,
            )
        statement = self._apply_provider_call_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        ).order_by(ProviderCallRecord.created_at.asc(), ProviderCallRecord.id.asc())
        return [int(value or 0) for value in self.session.scalars(statement)]

    def aggregate_runs_window(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
        profile_id: str | None = None,
    ) -> dict[str, object]:
        normalized_site_ids = self._normalize_site_ids(site_ids)
        if normalized_site_ids is not None and not normalized_site_ids:
            return {
                "runs_total": 0,
                "success_total": 0,
                "fallback_total": 0,
                "last_seen_at": None,
                "active_sites_total": 0,
                "avg_latency_ms": 0,
            }
        run_latency_ms = self._run_latency_ms_expression()
        statement = select(
            func.count(RunRecord.run_id),
            func.sum(case((RunRecord.status == "succeeded", 1), else_=0)),
            func.sum(case((RunRecord.fallback_used.is_(True), 1), else_=0)),
            func.max(func.coalesce(RunRecord.finished_at, RunRecord.started_at)),
            func.count(distinct(RunRecord.site_id)),
            func.avg(run_latency_ms) if run_latency_ms is not None else func.null(),
        )
        if normalized_site_ids is not None:
            statement = statement.where(RunRecord.site_id.in_(normalized_site_ids))
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if profile_id:
            statement = statement.where(RunRecord.profile_id == profile_id)
        statement = self._apply_run_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        )
        (
            runs_total,
            success_total,
            fallback_total,
            last_seen_at,
            active_sites_total,
            avg_latency_ms,
        ) = self.session.execute(statement).one()
        return {
            "runs_total": int(runs_total or 0),
            "success_total": int(success_total or 0),
            "fallback_total": int(fallback_total or 0),
            "last_seen_at": last_seen_at,
            "active_sites_total": int(active_sites_total or 0),
            "avg_latency_ms": int(round(float(avg_latency_ms or 0))),
        }

    def list_run_latency_values_window(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
        profile_id: str | None = None,
    ) -> list[int]:
        normalized_site_ids = self._normalize_site_ids(site_ids)
        if normalized_site_ids is not None and not normalized_site_ids:
            return []
        run_latency_ms = self._run_latency_ms_expression()
        if run_latency_ms is None:
            return []
        statement = select(run_latency_ms).where(
            RunRecord.started_at.is_not(None),
            RunRecord.finished_at.is_not(None),
        )
        if normalized_site_ids is not None:
            statement = statement.where(RunRecord.site_id.in_(normalized_site_ids))
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if profile_id:
            statement = statement.where(RunRecord.profile_id == profile_id)
        statement = self._apply_run_window_filters(
            statement,
            start_at=start_at,
            end_at=end_at,
        ).order_by(RunRecord.started_at.asc(), RunRecord.run_id.asc())
        return [int(value or 0) for value in self.session.scalars(statement)]

    def list_health_snapshots(
        self,
        instance_ids: list[str] | None = None,
    ) -> list[HealthSnapshot]:
        statement = select(HealthSnapshot).order_by(
            HealthSnapshot.measured_at.asc(),
            HealthSnapshot.id.asc(),
        )
        if instance_ids is not None:
            if not instance_ids:
                return []
            statement = statement.where(HealthSnapshot.instance_id.in_(instance_ids))
        return list(self.session.scalars(statement))

    def list_latest_health_snapshots(
        self,
        instance_ids: list[str] | None = None,
    ) -> list[HealthSnapshot]:
        if instance_ids is not None and not instance_ids:
            return []

        latest_timestamps_statement = select(
            HealthSnapshot.instance_id.label("instance_id"),
            func.max(HealthSnapshot.measured_at).label("measured_at"),
        ).where(HealthSnapshot.instance_id.is_not(None))
        if instance_ids is not None:
            latest_timestamps_statement = latest_timestamps_statement.where(
                HealthSnapshot.instance_id.in_(instance_ids)
            )
        latest_timestamps = latest_timestamps_statement.group_by(
            HealthSnapshot.instance_id
        ).subquery()

        latest_ids = (
            select(func.max(HealthSnapshot.id))
            .join(
                latest_timestamps,
                and_(
                    HealthSnapshot.instance_id == latest_timestamps.c.instance_id,
                    HealthSnapshot.measured_at == latest_timestamps.c.measured_at,
                ),
            )
            .group_by(HealthSnapshot.instance_id)
        )
        statement = (
            select(HealthSnapshot)
            .where(HealthSnapshot.id.in_(latest_ids))
            .order_by(HealthSnapshot.instance_id.asc(), HealthSnapshot.id.asc())
        )
        return list(self.session.scalars(statement))

    def upsert_usage_rollup(
        self,
        *,
        rollup_key: str,
        site_scope: str,
        scope_kind: str,
        scope_id: str,
        payload_json: dict[str, object],
    ) -> UsageRollup:
        rollup = self.session.get(UsageRollup, rollup_key)
        if rollup is None:
            rollup = UsageRollup(
                rollup_key=rollup_key,
                site_scope=site_scope,
                scope_kind=scope_kind,
                scope_id=scope_id,
                payload_json=payload_json,
            )
            self.session.add(rollup)
        else:
            rollup.site_scope = site_scope
            rollup.scope_kind = scope_kind
            rollup.scope_id = scope_id
            rollup.payload_json = payload_json

        self.session.flush()
        return rollup

    def list_usage_rollups(
        self,
        *,
        site_scope: str | None = None,
        scope_kind: str | None = None,
    ) -> list[UsageRollup]:
        statement = select(UsageRollup).order_by(
            UsageRollup.site_scope.asc(),
            UsageRollup.scope_kind.asc(),
            UsageRollup.scope_id.asc(),
        )
        if site_scope is not None:
            statement = statement.where(UsageRollup.site_scope == site_scope)
        if scope_kind is not None:
            statement = statement.where(UsageRollup.scope_kind == scope_kind)
        return list(self.session.scalars(statement))

    def _apply_run_window_filters(
        self,
        statement: Select,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> Select:
        if start_at is not None:
            statement = statement.where(
                RunRecord.started_at.is_not(None), RunRecord.started_at >= start_at
            )
        if end_at is not None:
            statement = statement.where(
                RunRecord.started_at.is_not(None), RunRecord.started_at <= end_at
            )
        return statement

    def _apply_provider_call_window_filters(
        self,
        statement: Select,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> Select:
        if start_at is not None:
            statement = statement.where(
                ProviderCallRecord.created_at.is_not(None),
                ProviderCallRecord.created_at >= start_at,
            )
        if end_at is not None:
            statement = statement.where(
                ProviderCallRecord.created_at.is_not(None),
                ProviderCallRecord.created_at <= end_at,
            )
        return statement

    def _run_latency_ms_expression(self) -> ColumnElement | None:
        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite":
            return cast(
                (func.julianday(RunRecord.finished_at) - func.julianday(RunRecord.started_at))
                * 86400000.0,
                Integer,
            )
        if dialect_name in {"postgresql", "postgres"}:
            return cast(
                func.extract("epoch", RunRecord.finished_at - RunRecord.started_at) * 1000.0,
                Integer,
            )
        return None

    def _empty_provider_call_metrics(self) -> dict[str, object]:
        return {
            "calls_total": 0,
            "success_total": 0,
            "fallback_total": 0,
            "avg_latency_ms": 0,
            "tokens_in_total": 0,
            "tokens_out_total": 0,
            "cost_total": 0.0,
            "last_seen_at": None,
        }
