"""Unit tests for the universal change ledger: serialisation, hook, and revert."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser
from app.models.change_ledger import ChangeLedgerEntry
from app.models.page import CustomPage
from app.services import change_ledger as ledger


def _result(value: object) -> MagicMock:
    """Build a mock execute() result whose scalar_one_or_none returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestSerialize:
    def test_serialize_row_coerces_temporal_values(self) -> None:
        page = CustomPage(id=3, org_id=1, title="Acme", slug="acme", content="<p></p>")
        page.created_at = datetime(2026, 1, 2, 3, 4, 5)

        snap = ledger.serialize_row(page)

        assert snap["title"] == "Acme"
        assert snap["created_at"] == "2026-01-02T03:04:05"

    def test_serialize_row_non_mapped_returns_empty(self) -> None:
        assert ledger.serialize_row(MagicMock()) == {}

    def test_compute_diff_reports_only_changed_fields(self) -> None:
        diff = ledger.compute_diff({"a": 1, "b": 2}, {"a": 1, "b": 9})

        assert diff == [{"field": "b", "old": 2, "new": 9}]


class TestContext:
    def test_ctx_for_marks_source_and_group(self, mock_admin_user: CurrentUser) -> None:
        ctx = ledger.ctx_for(mock_admin_user)

        assert ctx.source == "user"
        assert ctx.org_id == 1
        assert ctx.actor_user_id == 1
        assert len(ctx.correlation_id) == 32


class TestLogHook:
    @pytest.mark.asyncio
    async def test_log_create_adds_entry_with_after_snapshot(
        self, mock_db_session: AsyncMock, mock_admin_user: CurrentUser
    ) -> None:
        page = CustomPage(id=7, org_id=1, title="New", slug="new", content="")

        await ledger.log_create(
            mock_db_session,
            ctx=ledger.ctx_for(mock_admin_user),
            resource_type="custom_page",
            obj=page,
            resource_name="New",
        )

        added = mock_db_session.add.call_args[0][0]
        assert added.action == "create"
        assert added.resource_id == 7
        assert added.after["title"] == "New"
        assert added.before is None


class TestRevertEngine:
    @pytest.mark.asyncio
    async def test_revert_create_deletes_and_records_inverse(
        self, mock_db_session: AsyncMock
    ) -> None:
        current = CustomPage(id=5, org_id=1, title="Acme", slug="acme", content="")
        mock_db_session.execute = AsyncMock(return_value=_result(current))
        mock_db_session.delete = AsyncMock()
        entry = ChangeLedgerEntry(
            id=1, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="create", before=None, after={"id": 5, "title": "Acme"},
        )

        outcome = await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

        mock_db_session.delete.assert_awaited_once_with(current)
        assert entry.reverted_at is not None
        assert outcome.inverse_action == "delete"
        inverse = mock_db_session.add.call_args[0][0]
        assert inverse.action == "delete" and inverse.revert_of_id == 1

    @pytest.mark.asyncio
    async def test_revert_update_restores_before(self, mock_db_session: AsyncMock) -> None:
        current = CustomPage(id=5, org_id=1, title="Renamed", slug="acme", content="")
        after = ledger.serialize_row(current)
        mock_db_session.execute = AsyncMock(return_value=_result(current))
        entry = ChangeLedgerEntry(
            id=2, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="update", before={"title": "Original"}, after=after,
        )

        await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

        assert current.title == "Original"
        assert entry.reverted_at is not None

    @pytest.mark.asyncio
    async def test_revert_update_conflicts_when_changed_since(
        self, mock_db_session: AsyncMock
    ) -> None:
        current = CustomPage(id=5, org_id=1, title="ChangedBySomeoneElse", slug="a", content="")
        mock_db_session.execute = AsyncMock(return_value=_result(current))
        entry = ChangeLedgerEntry(
            id=3, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="update", before={"title": "Original"},
            after={"title": "WhatWeExpected"},
        )

        with pytest.raises(ledger.RevertConflictError):
            await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

    @pytest.mark.asyncio
    async def test_revert_already_reverted_conflicts(self, mock_db_session: AsyncMock) -> None:
        entry = ChangeLedgerEntry(
            id=4, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="create", before=None, after={"id": 5},
        )
        entry.reverted_at = datetime(2026, 1, 1)

        with pytest.raises(ledger.RevertConflictError):
            await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

    @pytest.mark.asyncio
    async def test_revert_unknown_resource_type_unavailable(
        self, mock_db_session: AsyncMock
    ) -> None:
        entry = ChangeLedgerEntry(
            id=5, org_id=1, correlation_id="c", source="user", resource_type="nope",
            resource_id=5, action="create", before=None, after={"id": 5},
        )

        with pytest.raises(ledger.RevertUnavailableError):
            await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)


class TestPreDeleteHook:
    """A create-revert runs the resource's pre_delete hook before deleting.

    Some resources acquire children after they are created that hold a NO ACTION
    foreign key — a report gains runs — and the delete fails on the constraint
    until the link is cleared. Without the hook, reverting the creation of a
    report that has ever run raises an IntegrityError the caller reports as
    "reverting would violate a data constraint".
    """

    @pytest.mark.asyncio
    async def test_pre_delete_runs_before_the_row_is_deleted(
        self, mock_db_session: AsyncMock
    ) -> None:
        current = CustomPage(id=5, org_id=1, title="Acme", slug="acme", content="")
        mock_db_session.execute = AsyncMock(return_value=_result(current))
        order: list[str] = []
        mock_db_session.delete = AsyncMock(side_effect=lambda _: order.append("delete"))

        async def hook(_db: object, _obj: object) -> None:
            order.append("pre_delete")

        resource = MagicMock(model=CustomPage, pre_delete=hook, parent_fks={})
        entry = ChangeLedgerEntry(
            id=1, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="create", before=None, after={"id": 5},
        )

        with patch.object(ledger, "_get_resource", MagicMock(return_value=resource)):
            await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

        assert order == ["pre_delete", "delete"]

    @pytest.mark.asyncio
    async def test_a_resource_without_a_hook_still_reverts(
        self, mock_db_session: AsyncMock
    ) -> None:
        current = CustomPage(id=5, org_id=1, title="Acme", slug="acme", content="")
        mock_db_session.execute = AsyncMock(return_value=_result(current))
        mock_db_session.delete = AsyncMock()
        entry = ChangeLedgerEntry(
            id=1, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="create", before=None, after={"id": 5},
        )

        await ledger.revert_entry(mock_db_session, entry, actor_user_id=2)

        mock_db_session.delete.assert_awaited_once_with(current)


class TestJsonIdRemap:
    """A grouped revert lets JSON-held references follow ids that changed.

    Recreating a deleted row assigns it a fresh primary key. `parent_fks` fixes
    real foreign keys; a reference a column merely *contains* — a nav link's
    "/dashboard/{id}" href — needs the resource's own remap hook, or the
    restored link points at an id nothing has.
    """

    @pytest.mark.asyncio
    async def test_remap_runs_for_a_resource_that_declares_it(
        self, mock_db_session: AsyncMock
    ) -> None:
        settings_row = MagicMock()
        mock_db_session.execute = AsyncMock(return_value=_result(settings_row))
        seen: list[dict] = []
        resource = MagicMock(
            model=CustomPage, remap_ids=lambda _row, maps: seen.append(maps), parent_fks={}
        )
        entry = ChangeLedgerEntry(
            id=1, org_id=1, correlation_id="c", source="user", resource_type="org_settings",
            resource_id=5, action="update", before={}, after={},
        )

        with patch.object(ledger, "_get_resource", MagicMock(return_value=resource)):
            await ledger._remap_json_ids(mock_db_session, [entry], {"dashboard": {7: 42}})

        assert seen == [{"dashboard": {7: 42}}]

    @pytest.mark.asyncio
    async def test_nothing_runs_when_no_id_changed(self, mock_db_session: AsyncMock) -> None:
        # The common case is a group whose rows kept their ids; it must not cost
        # a query per entry.
        mock_db_session.execute = AsyncMock()

        await ledger._remap_json_ids(mock_db_session, [MagicMock()], {})

        assert mock_db_session.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_a_resource_without_a_hook_is_skipped(
        self, mock_db_session: AsyncMock
    ) -> None:
        resource = MagicMock(model=CustomPage, remap_ids=None, parent_fks={})
        entry = ChangeLedgerEntry(
            id=1, org_id=1, correlation_id="c", source="user", resource_type="custom_page",
            resource_id=5, action="delete", before={}, after=None,
        )

        with patch.object(ledger, "_get_resource", MagicMock(return_value=resource)):
            await ledger._remap_json_ids(mock_db_session, [entry], {"dashboard": {7: 42}})

        assert mock_db_session.execute.await_count == 0
