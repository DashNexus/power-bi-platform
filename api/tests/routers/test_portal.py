"""Unit tests for portal feature gating and per-resource grant unlocking.

These cover the access-control surface most likely to leak data in a beta: which
features a user sees in their portal navigation, and whether a per-resource share
(ERD / data dictionary) unlocks the corresponding feature (lineage / governance)
even without the broad view permission.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _viewer(user_id: int = 2, org_id: int = 1) -> CurrentUser:
    """A non-admin user, so the permission/grant gate actually applies."""
    return CurrentUser(user_id=user_id, org_id=org_id, role="viewer", email="v@example.com")


def _first_result(obj: object | None) -> MagicMock:
    """A db.execute() result whose .first() returns obj (or None)."""
    result = MagicMock()
    result.first.return_value = obj
    return result


def _flag(feature_key: str, enabled: bool) -> MagicMock:
    flag = MagicMock()
    flag.feature_key = feature_key
    flag.enabled = enabled
    return flag


def _flags_result(flags: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = flags
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# _grant_unlocked_features
# ---------------------------------------------------------------------------


class TestGrantUnlockedFeatures:
    """A share of a specific resource unlocks its feature for the sharee.

    The nine existence checks are issued as one UNION ALL, so these tests shape a
    single result set of feature labels rather than counting queries. The union
    itself — join columns, org scoping — is exercised against a real database;
    mocks cannot catch a wrong foreign-key name.
    """

    @staticmethod
    def _returns(*features: str) -> AsyncMock:
        """A db.execute that answers the union with the given feature rows."""
        result = MagicMock()
        result.all.return_value = [(f,) for f in features]
        return AsyncMock(return_value=result)

    @pytest.mark.asyncio
    async def test_erd_grant_unlocks_lineage_only(self, mock_db_session: AsyncMock) -> None:
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("lineage")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"lineage"}

    @pytest.mark.asyncio
    async def test_dict_grant_unlocks_governance_only(self, mock_db_session: AsyncMock) -> None:
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("governance")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"governance"}

    @pytest.mark.asyncio
    async def test_dataset_grant_unlocks_manual_datasets_only(
        self, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("manual_datasets")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"manual_datasets"}

    @pytest.mark.asyncio
    async def test_several_grants_unlock_several_features(
        self, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("lineage", "governance", "pipelines")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"lineage", "governance", "pipelines"}

    @pytest.mark.asyncio
    async def test_duplicate_rows_collapse_to_one_feature(
        self, mock_db_session: AsyncMock
    ) -> None:
        """Clients and projects both unlock project_planning; the set dedupes them."""
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("project_planning", "project_planning")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"project_planning"}

    @pytest.mark.asyncio
    async def test_no_grants_unlocks_nothing(self, mock_db_session: AsyncMock) -> None:
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns()
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == set()

    @pytest.mark.asyncio
    async def test_all_checks_go_out_as_one_round_trip(
        self, mock_db_session: AsyncMock
    ) -> None:
        """Regression: this ran nine sequential queries on every page load."""
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns()
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[7])):
            await _grant_unlocked_features(_viewer(), mock_db_session)

        assert mock_db_session.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_a_user_with_no_roles_still_checks_direct_user_grants(
        self, mock_db_session: AsyncMock
    ) -> None:
        """Legacy per-user grants must still resolve when the user holds no roles."""
        from app.routers.portal import _grant_unlocked_features

        mock_db_session.execute = self._returns("governance")
        with patch("app.services.permissions.get_user_role_ids", new=AsyncMock(return_value=[])):
            unlocked = await _grant_unlocked_features(_viewer(), mock_db_session)
        assert unlocked == {"governance"}


class TestGetPortalFeatures:
    """GET /portal/features — effective flag = org flag AND (permission OR grant)."""

    async def _call(
        self,
        db: AsyncMock,
        user: CurrentUser,
        *,
        perms: set[str],
        grant_unlocked: set[str],
        flags: list,
    ) -> dict[str, dict]:
        from app.routers.portal import get_portal_features

        db.execute = AsyncMock(return_value=_flags_result(flags))
        with (
            patch(
                "app.services.permissions.get_user_permission_keys",
                new=AsyncMock(return_value=perms),
            ),
            patch(
                "app.routers.portal._grant_unlocked_features",
                new=AsyncMock(return_value=grant_unlocked),
            ),
        ):
            result = await get_portal_features(current_user=user, db=db)
        return {f["feature_key"]: f for f in result}

    @pytest.mark.asyncio
    async def test_admin_sees_all_org_enabled_features(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Admin bypasses the permission gate — every org-enabled feature is on."""
        monkeypatch.delenv("FEATURE_GOVERNANCE", raising=False)
        monkeypatch.delenv("FEATURE_LINEAGE", raising=False)

        by_key = await self._call(
            mock_db_session,
            mock_admin_user,
            perms=set(),  # admin holds no explicit perms in this mock...
            grant_unlocked=set(),  # ...and no grants...
            flags=[_flag("governance", True), _flag("lineage", True)],
        )

        assert by_key["governance"]["enabled"] is True  # ...yet still sees them
        assert by_key["lineage"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_viewer_with_permission_sees_feature(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_GOVERNANCE", raising=False)

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms={"data_dictionary.view"},
            grant_unlocked=set(),
            flags=[_flag("governance", True)],
        )

        assert by_key["governance"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_viewer_without_permission_but_with_grant_sees_feature(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A per-resource share unlocks the feature even with no view permission."""
        monkeypatch.delenv("FEATURE_LINEAGE", raising=False)

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms=set(),  # no erd.view / erd.manage
            grant_unlocked={"lineage"},  # but an ERD was shared to their role
            flags=[_flag("lineage", True)],
        )

        assert by_key["lineage"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_viewer_without_permission_or_grant_is_denied(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_GOVERNANCE", raising=False)

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms=set(),
            grant_unlocked=set(),
            flags=[_flag("governance", True)],
        )

        assert by_key["governance"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_org_disabled_flag_overrides_permission(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with the permission, an org-disabled feature stays off."""
        monkeypatch.delenv("FEATURE_GOVERNANCE", raising=False)

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms={"data_dictionary.manage"},
            grant_unlocked=set(),
            flags=[_flag("governance", False)],  # org flag off
        )

        assert by_key["governance"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_org_disabled_flag_overrides_grant(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A grant cannot resurrect a feature the org has turned off."""
        monkeypatch.delenv("FEATURE_LINEAGE", raising=False)

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms=set(),
            grant_unlocked={"lineage"},
            flags=[_flag("lineage", False)],
        )

        assert by_key["lineage"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_env_override_forces_enabled_and_flags_override(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FEATURE_* env var wins over the DB flag and is reported as an override."""
        monkeypatch.setenv("FEATURE_GOVERNANCE", "true")

        by_key = await self._call(
            mock_db_session,
            _viewer(),
            perms={"data_dictionary.view"},
            grant_unlocked=set(),
            flags=[_flag("governance", False)],  # DB says off, env says on
        )

        assert by_key["governance"]["enabled"] is True
        assert by_key["governance"]["env_override"] is True
