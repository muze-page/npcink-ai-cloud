from __future__ import annotations

import pytest

from app.domain.commercial.errors import CommercialPermissionError
from app.domain.commercial.identity import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    IDENTITY_TYPE_USER,
    PLATFORM_ADMIN_ALLOWED_ROLES,
    USER_ALLOWED_ROLES,
    normalize_user_role,
)


def test_launch_identity_model_has_only_platform_admin_and_user() -> None:
    assert IDENTITY_TYPE_PLATFORM_ADMIN == "platform_admin"
    assert IDENTITY_TYPE_USER == "user"
    assert PLATFORM_ADMIN_ALLOWED_ROLES == {"platform_admin"}
    assert USER_ALLOWED_ROLES == {"user"}


def test_operator_role_is_not_accepted_before_the_role_is_launched() -> None:
    with pytest.raises(CommercialPermissionError) as error:
        normalize_user_role("operator")

    assert error.value.error_code == "service.portal_user_role_invalid"
