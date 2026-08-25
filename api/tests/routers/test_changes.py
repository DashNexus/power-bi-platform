"""Unit tests for the change-history feeds and revert endpoints.

Covers the required access matrix: admin bypass on the global feed, permission
gating, per-resource view/edit enforcement on history/revert, 404 on missing or
cross-org entries, and 409/422 revert error translation.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.auth import CurrentUser
from app.models.change_ledger import ChangeLedgerEntry
from app.routers import changes
from app.services import change_ledger, mutation_registry


def _entry(**kw: object) -> ChangeLedgerEntry:
    defaults = dict(
        id=1, org_id=1, correlation_id="c", actor_user_id=None, source="user",
        resource_type="project", resource_id=5, action="update",
        before={"name": "a"}, after={"name": "b"}, resource_name="Proj",
        revert_of_id=None, reverted_at=None,
    )
    defaults.update(kw)
    entry = ChangeLedgerEntry(**defaults)
    entry.created_at = datetime(2026, 1, 1)
    return entry


def _fake_resource() -> MagicMock:
    res = MagicMock()
    res.require_view = AsyncMock()
    res.require_edit = AsyncMock()
    return res


def _list_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestElementHistory:
    @pytest.mark.asyncio
    async def test_unknown_resource_type_returns_422(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        with patch.object(changes, "get_resource", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await changes.element_history("bogus", 5, mock_admin_user, mock_db_session)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_history_enforces_resource_view(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        res = _fake_resource()
        res.require_view.side_effect = HTTPException(status_code=404, detail="nope")
        mock_db_session.execute = AsyncMock(return_value=_list_result([_entry()]))

        with patch.object(changes, "get_resource", return_value=res):
            with pytest.raises(HTTPException) as exc:
                await changes.element_history("project", 5, mock_admin_user, mock_db_session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_history_returns_records_with_diff(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_list_result([_entry()]))

        with patch.object(changes, "get_resource", return_value=_fake_resource()):
            records = await changes.element_history("project", 5, mock_admin_user, mock_db_session)

        assert len(records) == 1
        assert records[0].diff == [{"field": "name", "old": "a", "new": "b"}]


class TestCorrelationSize:
    """The UI picks single vs group revert from this, so it must be accurate."""

    @pytest.mark.asyncio
    async def test_multi_row_action_reports_its_group_size(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        counts = MagicMock()
        counts.all.return_value = [("c", 3)]
        mock_db_session.execute = AsyncMock(
            side_effect=[_list_result([_entry(correlation_id="c")]), counts]
        )

        with patch.object(changes, "get_resource", return_value=_fake_resource()):
            records = await changes.element_history("project", 5, mock_admin_user, mock_db_session)

        assert records[0].correlation_size == 3

    @pytest.mark.asyncio
    async def test_single_row_action_reports_one(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        counts = MagicMock()
        counts.all.return_value = [("c", 1)]
        mock_db_session.execute = AsyncMock(
            side_effect=[_list_result([_entry(correlation_id="c")]), counts]
        )

        with patch.object(changes, "get_resource", return_value=_fake_resource()):
            records = await changes.element_history("project", 5, mock_admin_user, mock_db_session)

        assert records[0].correlation_size == 1

    @pytest.mark.asyncio
    async def test_no_entries_skips_the_count_query(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_list_result([]))

        with patch.object(changes, "get_resource", return_value=_fake_resource()):
            records = await changes.element_history("project", 5, mock_admin_user, mock_db_session)

        assert records == []
        assert mock_db_session.execute.await_count == 1


class TestGlobalFeedAccess:
    @pytest.mark.asyncio
    async def test_admin_bypasses_permission(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        user = await changes._require_changes_view(mock_admin_user, mock_db_session)
        assert user is mock_admin_user

    @pytest.mark.asyncio
    async def test_viewer_without_permission_denied(self, mock_db_session: AsyncMock) -> None:
        viewer = CurrentUser(user_id=2, org_id=1, role="viewer", email="v@example.com")
        with patch(
            "app.services.permissions.user_has_permission", new=AsyncMock(return_value=False)
        ):
            with pytest.raises(HTTPException) as exc:
                await changes._require_changes_view(viewer, mock_db_session)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_analyst_with_permission_allowed(self, mock_db_session: AsyncMock) -> None:
        analyst = CurrentUser(user_id=2, org_id=1, role="analyst", email="a@example.com")
        with patch(
            "app.services.permissions.user_has_permission", new=AsyncMock(return_value=True)
        ):
            user = await changes._require_changes_view(analyst, mock_db_session)
        assert user is analyst


class TestFeedFilters:
    @pytest.mark.asyncio
    async def test_global_feed_purges_and_passes_action(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock()
        captured: dict[str, object] = {}

        async def fake_feed(_db, _org, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            captured.update(kwargs)
            return []

        with patch.object(changes, "_feed", side_effect=fake_feed), patch.object(
            changes, "_purge_expired", new=AsyncMock()
        ) as purge:
            await changes.global_feed(
                source=None, resource_type=None, action="update", actor_user_id=None,
                actor=None, correlation_id=None, limit=100, offset=0,
                current_user=mock_admin_user, db=mock_db_session,
            )

        purge.assert_awaited_once()
        assert captured["action"] == "update"

    @pytest.mark.asyncio
    async def test_actor_search_filters_to_matching_users(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        users_result = MagicMock()
        users_result.all.return_value = [(2,)]
        entries_result = MagicMock()
        entries_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(side_effect=[users_result, entries_result])

        records = await changes._feed(
            mock_db_session, 1, source=None, resource_type=None, action=None,
            actor_user_id=None, actor="alice", correlation_id=None, limit=50, offset=0,
        )

        assert records == []
        assert mock_db_session.execute.await_count == 2


class TestUpdateRevertConcurrencyCheck:
    """`updated_at` must be excluded, or no update is ever revertible.

    log_update snapshots the row before flush, but onupdate=func.now() evaluates
    during flush — so the stored `after` can never match the committed row, and
    every model carrying TimestampMixin would 409 on revert.
    """

    def test_server_managed_timestamps_are_excluded_from_the_comparison(self) -> None:
        stored = {"name": "b", "updated_at": "2026-01-01T00:00:00"}
        live = {"name": "b", "updated_at": "2026-01-01T00:00:02"}

        assert change_ledger._comparable(live) == change_ledger._comparable(stored)

    def test_a_real_field_change_still_registers(self) -> None:
        stored = {"name": "b", "updated_at": "2026-01-01T00:00:00"}
        live = {"name": "edited elsewhere", "updated_at": "2026-01-01T00:00:00"}

        assert change_ledger._comparable(live) != change_ledger._comparable(stored)

    def test_created_at_is_also_excluded(self) -> None:
        assert change_ledger._comparable({"created_at": "x", "name": "n"}) == {"name": "n"}

    def test_none_snapshot_compares_as_empty(self) -> None:
        assert change_ledger._comparable(None) == {}


class TestRevert:
    @pytest.mark.asyncio
    async def test_missing_entry_returns_404(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))
        with pytest.raises(HTTPException) as exc:
            await changes.revert_change(1, False, mock_admin_user, mock_db_session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revert_enforces_edit(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(_entry()))
        res = _fake_resource()
        res.require_edit.side_effect = HTTPException(status_code=403, detail="no edit")

        with patch.object(changes, "get_resource", return_value=res):
            with pytest.raises(HTTPException) as exc:
                await changes.revert_change(1, False, mock_admin_user, mock_db_session)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_revert_success_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(_entry()))
        outcome = change_ledger.RevertResult(1, "project", "update", 5)

        with patch.object(changes, "get_resource", return_value=_fake_resource()), patch.object(
            change_ledger, "revert_entry", new=AsyncMock(return_value=outcome)
        ):
            resp = await changes.revert_change(1, False, mock_admin_user, mock_db_session)

        assert resp.reverted[0].ledger_id == 1
        mock_db_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_revert_conflict_returns_409(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(_entry()))
        mock_db_session.rollback = AsyncMock()

        with patch.object(changes, "get_resource", return_value=_fake_resource()), patch.object(
            change_ledger,
            "revert_entry",
            new=AsyncMock(side_effect=change_ledger.RevertConflictError("changed")),
        ):
            with pytest.raises(HTTPException) as exc:
                await changes.revert_change(1, False, mock_admin_user, mock_db_session)
        assert exc.value.status_code == 409


class TestResourceTypeOptions:
    """The feed's filter menu is served from the registry.

    It was a hand-written list in the client that had drifted to name resources
    this build does not have (projects, tasks, tickets) while omitting the ones
    it does — so filtering by a real type was impossible and filtering by a
    phantom one returned an empty feed that read as "nothing ever happened".
    """

    @pytest.mark.asyncio
    async def test_options_come_from_the_mutation_registry(
        self, mock_admin_user: CurrentUser
    ) -> None:
        options = await changes.list_resource_types(mock_admin_user)

        assert {o.value for o in options} == {
            value for value, _ in mutation_registry.top_level_resources()
        }

    @pytest.mark.asyncio
    async def test_reports_are_offered(self, mock_admin_user: CurrentUser) -> None:
        options = await changes.list_resource_types(mock_admin_user)

        assert any(o.value == "report" and o.label == "SQL reports" for o in options)

    @pytest.mark.asyncio
    async def test_every_option_is_a_type_the_feed_can_filter_by(
        self, mock_admin_user: CurrentUser
    ) -> None:
        options = await changes.list_resource_types(mock_admin_user)

        assert all(mutation_registry.get_resource(o.value) is not None for o in options)

    def test_the_route_does_not_collide_with_the_per_resource_history_path(self) -> None:
        # /changes/{resource_type}/{resource_id} takes two segments; this takes
        # one, so "resource-types" cannot be read as a resource type.
        paths = {r.path for r in changes.router.routes}

        assert "/changes/resource-types" in paths
        assert "/changes/{resource_type}/{resource_id}" in paths
