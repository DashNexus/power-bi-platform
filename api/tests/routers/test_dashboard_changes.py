"""Tests for dashboard change-ledger wiring and its access guards.

A dashboard delete cascades to its filters and shares, so the delete has to
snapshot all three under one correlation id or a revert brings the dashboard back
stripped of both. These tests pin that, plus the admin-only guard the ledger's
history and revert endpoints inherit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.middleware.auth import CurrentUser
from app.models.change_ledger import ChangeLedgerEntry
from app.models.dashboard import DashboardConfig, DashboardFilter, DashboardPermission
from app.routers import dashboards
from app.services.mutation_registry import get_resource


def _dashboard(**overrides: object) -> DashboardConfig:
    defaults = dict(
        id=7, org_id=1, name="Sales", description=None, slug="sales",
        embed_type="powerbi", bi_connection_id=6, settings={}, required_role="viewer",
        is_active=True, tags=None, created_by_user_id=1,
    )
    defaults.update(overrides)
    return DashboardConfig(**defaults)


def _scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _list(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _ledger_entries(db: AsyncMock) -> list[ChangeLedgerEntry]:
    return [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ChangeLedgerEntry)
    ]


class TestDeleteDashboardLedger:
    @staticmethod
    def _db(
        filters: list[DashboardFilter], grants: list[DashboardPermission]
    ) -> AsyncMock:
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_scalar(_dashboard()), _list(filters), _list(grants)]
        )
        return db

    @pytest.mark.asyncio
    async def test_delete_records_a_ledger_entry_for_the_dashboard(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = self._db([], [])

        await dashboards.delete_dashboard(7, current_user=mock_admin_user, db=db)

        entries = _ledger_entries(db)
        assert [(e.resource_type, e.action) for e in entries] == [("dashboard", "delete")]

    @pytest.mark.asyncio
    async def test_delete_snapshots_the_row_so_a_revert_can_recreate_it(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = self._db([], [])

        await dashboards.delete_dashboard(7, current_user=mock_admin_user, db=db)

        before = _ledger_entries(db)[0].before
        assert before["slug"] == "sales"
        assert before["embed_type"] == "powerbi"
        assert before["bi_connection_id"] == 6

    @pytest.mark.asyncio
    async def test_delete_also_logs_cascade_deleted_filters_and_shares(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = self._db(
            [
                DashboardFilter(
                    id=1, dashboard_id=7, filter_key="region", filter_label="Region",
                    filter_type="string", default_value=None, user_attribute=None,
                    is_required=False, display_order=0,
                )
            ],
            [DashboardPermission(id=2, dashboard_id=7, user_id=None, role_id=4)],
        )

        await dashboards.delete_dashboard(7, current_user=mock_admin_user, db=db)

        assert [e.resource_type for e in _ledger_entries(db)] == [
            "dashboard",
            "dashboard_filter",
            "dashboard_permission",
        ]

    @pytest.mark.asyncio
    async def test_child_entries_share_the_parents_correlation_id(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = self._db(
            [
                DashboardFilter(
                    id=1, dashboard_id=7, filter_key="region", filter_label="Region",
                    filter_type="string", default_value=None, user_attribute=None,
                    is_required=False, display_order=0,
                )
            ],
            [],
        )

        await dashboards.delete_dashboard(7, current_user=mock_admin_user, db=db)

        correlation_ids = {e.correlation_id for e in _ledger_entries(db)}
        assert len(correlation_ids) == 1

    @pytest.mark.asyncio
    async def test_missing_dashboard_returns_404_and_logs_nothing(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=_scalar(None))

        with pytest.raises(HTTPException) as exc_info:
            await dashboards.delete_dashboard(7, current_user=mock_admin_user, db=db)

        assert exc_info.value.status_code == 404
        assert _ledger_entries(db) == []


class TestDashboardLedgerGuard:
    """History and revert follow who may edit the config, not who may view it."""

    @pytest.mark.asyncio
    async def test_admin_is_allowed(self, mock_admin_user: CurrentUser) -> None:
        resource = get_resource("dashboard")
        assert resource is not None

        await resource.require_edit(AsyncMock(), mock_admin_user, 7, None)

    @pytest.mark.asyncio
    async def test_superadmin_is_allowed(self, mock_superadmin_user: CurrentUser) -> None:
        resource = get_resource("dashboard")
        assert resource is not None

        await resource.require_edit(AsyncMock(), mock_superadmin_user, 7, None)

    @pytest.mark.asyncio
    async def test_analyst_is_denied_even_with_a_view_grant(self) -> None:
        analyst = CurrentUser(user_id=2, org_id=1, role="analyst", email="a@example.com")
        resource = get_resource("dashboard")
        assert resource is not None

        with pytest.raises(HTTPException) as exc_info:
            await resource.require_edit(AsyncMock(), analyst, 7, None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_is_denied(self) -> None:
        viewer = CurrentUser(user_id=3, org_id=1, role="viewer", email="v@example.com")
        resource = get_resource("dashboard")
        assert resource is not None

        with pytest.raises(HTTPException):
            await resource.require_view(AsyncMock(), viewer, 7, None)

    @pytest.mark.asyncio
    async def test_guard_passes_when_the_row_is_already_deleted(
        self, mock_admin_user: CurrentUser
    ) -> None:
        """A delete-revert guard runs with no live row, so it must not 404."""
        resource = get_resource("dashboard")
        assert resource is not None

        await resource.require_edit(AsyncMock(), mock_admin_user, None, {"name": "Sales"})


class TestDashboardRegistration:
    def test_dashboard_is_revertible(self) -> None:
        assert get_resource("dashboard") is not None

    def test_filters_remap_onto_the_recreated_dashboard(self) -> None:
        resource = get_resource("dashboard_filter")
        assert resource is not None
        assert resource.parent_fks == {"dashboard_id": "dashboard"}

    def test_shares_remap_onto_the_recreated_dashboard(self) -> None:
        resource = get_resource("dashboard_permission")
        assert resource is not None
        assert resource.parent_fks == {"dashboard_id": "dashboard"}

    def test_share_is_named_by_the_principal_it_targets(self) -> None:
        resource = get_resource("dashboard_permission")
        assert resource is not None

        by_role = resource.resource_name(DashboardPermission(id=1, dashboard_id=7, role_id=4))
        by_user = resource.resource_name(DashboardPermission(id=2, dashboard_id=7, user_id=9))

        assert (by_role, by_user) == ("role 4", "user 9")

    def test_custom_page_is_revertible(self) -> None:
        assert get_resource("custom_page") is not None
