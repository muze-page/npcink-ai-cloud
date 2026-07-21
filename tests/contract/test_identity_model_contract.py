from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.domain.commercial.errors import CommercialPermissionError
from app.domain.commercial.identity import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    IDENTITY_TYPE_USER,
    PLATFORM_ADMIN_ALLOWED_ROLES,
    USER_ALLOWED_ACTION_PROVISION_SITES,
    USER_ALLOWED_ROLES,
    _new_principal_id,
    normalize_user_role,
    resolve_principal_allowed_actions,
)


def test_launch_identity_model_has_only_platform_admin_and_user() -> None:
    assert IDENTITY_TYPE_PLATFORM_ADMIN == "platform_admin"
    assert IDENTITY_TYPE_USER == "user"
    assert PLATFORM_ADMIN_ALLOWED_ROLES == {"platform_admin"}
    assert USER_ALLOWED_ROLES == {"user"}


def test_portal_user_actions_keep_addon_provision_without_key_management() -> None:
    actions = set(resolve_principal_allowed_actions())

    assert USER_ALLOWED_ACTION_PROVISION_SITES in actions
    assert actions == {
        "view_sites",
        "view_usage",
        "view_billing",
        "view_audit",
        "provision_sites",
        "remove_sites",
    }


def test_operator_role_is_not_accepted_before_the_role_is_launched() -> None:
    with pytest.raises(CommercialPermissionError) as error:
        normalize_user_role("operator")

    assert error.value.error_code == "service.portal_user_role_invalid"


def test_principal_ids_use_the_frozen_server_generated_format() -> None:
    principal_id = _new_principal_id()

    assert principal_id.startswith("prn_")
    assert len(principal_id) == 36
    assert int(principal_id.removeprefix("prn_"), 16) >= 0


def test_provider_binding_cannot_move_between_principals(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoopSession:
        def flush(self) -> None:
            return None

    binding = SimpleNamespace(
        principal_id="prn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        unionid_hash=None,
    )
    repository = CommercialRepository(cast(Any, NoopSession()))
    monkeypatch.setattr(
        repository,
        "get_identity_provider_binding",
        lambda **_kwargs: binding,
    )

    with pytest.raises(ValueError, match="principal_id is immutable"):
        repository.upsert_identity_provider_binding(
            binding_id="pib_test",
            principal_id="prn_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            provider="qq",
            external_subject_hash="subject-hash",
            unionid_hash=None,
        )

    assert binding.principal_id == "prn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
