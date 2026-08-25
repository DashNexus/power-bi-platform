"""Shared test fixtures.

Unit tests mock the database session and current user so they run without a
live PostgreSQL connection. Integration tests (marked @pytest.mark.integration)
hit a real database via TEST_DATABASE_URL.
"""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser

# Routers whose permission lookup is patched for unit tests. In production the
# built-in admin/superadmin roles carry every permission (see the initial
# migration's seed); unit tests mock the DB, so the grant is made directly here.
_PERMISSION_LOOKUPS = ("app.routers.data_dict.get_user_permission_keys",)


@pytest.fixture(autouse=True)
def grant_governance_permissions() -> Iterator[None]:
    """Give the mocked current user the resource permissions used in unit tests."""
    perms = {"data_dictionary.view", "data_dictionary.manage"}
    patchers = [patch(target, new=AsyncMock(return_value=perms)) for target in _PERMISSION_LOOKUPS]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


@pytest.fixture()
def mock_admin_user() -> CurrentUser:
    """Return a CurrentUser with admin role."""
    return CurrentUser(user_id=1, org_id=1, role="admin", email="admin@example.com")


@pytest.fixture()
def mock_superadmin_user() -> CurrentUser:
    """Return a CurrentUser with superadmin role."""
    return CurrentUser(user_id=1, org_id=1, role="superadmin", email="superadmin@example.com")


@pytest.fixture()
def mock_db_session() -> AsyncMock:
    """Return a mocked async SQLAlchemy session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session
