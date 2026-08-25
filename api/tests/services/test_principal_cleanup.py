"""Unit tests for the cleanup that replaced the user/role cascades.

Two behaviours matter and pull in opposite directions: a grant naming a deleted
principal must go, and a record of *who did something* must not. Deleting audit
history to delete a user would be the wrong trade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services import principal_cleanup

GRANT_TABLES = {
    "dashboard_permissions",
    "custom_page_permissions",
    "data_dictionary_permissions",
    "warehouse_connection_permissions",
    "data_pipeline_connection_permissions",
}


def _statements(db: AsyncMock) -> list[object]:
    return [call.args[0] for call in db.execute.await_args_list]


def _deleted_tables(db: AsyncMock) -> set[str]:
    return {
        s.table.name  # type: ignore[union-attr]
        for s in _statements(db)
        if s.__visit_name__ == "delete"  # type: ignore[union-attr]
    }


def _updated_tables(db: AsyncMock) -> set[str]:
    return {
        s.table.name  # type: ignore[union-attr]
        for s in _statements(db)
        if s.__visit_name__ == "update"  # type: ignore[union-attr]
    }


class TestRemoveUserGrants:
    @pytest.mark.asyncio
    async def test_deletes_every_grant_and_the_role_assignments(
        self, mock_db_session: AsyncMock
    ) -> None:
        await principal_cleanup.remove_user_grants(mock_db_session, user_id=7)

        assert _deleted_tables(mock_db_session) == GRANT_TABLES | {"user_roles"}

    @pytest.mark.asyncio
    async def test_keeps_audit_and_change_history_by_nulling_the_actor(
        self, mock_db_session: AsyncMock
    ) -> None:
        """History outlives the account — the pointer is cleared, not the row."""
        await principal_cleanup.remove_user_grants(mock_db_session, user_id=7)

        updated = _updated_tables(mock_db_session)

        assert {"audit_logs", "change_ledger"} <= updated
        assert "audit_logs" not in _deleted_tables(mock_db_session)
        assert "change_ledger" not in _deleted_tables(mock_db_session)

    @pytest.mark.asyncio
    async def test_clears_authorship_on_content_the_user_created(
        self, mock_db_session: AsyncMock
    ) -> None:
        await principal_cleanup.remove_user_grants(mock_db_session, user_id=7)

        assert {
            "custom_pages",
            "custom_page_versions",
            "dashboard_configs",
            "dashboard_config_versions",
        } <= _updated_tables(mock_db_session)

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db_session: AsyncMock) -> None:
        """The caller owns the transaction, so cleanup and delete land together."""
        await principal_cleanup.remove_user_grants(mock_db_session, user_id=7)

        mock_db_session.commit.assert_not_awaited()


class TestRemoveRoleGrants:
    @pytest.mark.asyncio
    async def test_deletes_every_grant_and_the_user_assignments(
        self, mock_db_session: AsyncMock
    ) -> None:
        await principal_cleanup.remove_role_grants(mock_db_session, role_id=3)

        assert _deleted_tables(mock_db_session) == GRANT_TABLES | {"user_roles"}

    @pytest.mark.asyncio
    async def test_keeps_a_pending_invitation_by_clearing_its_role(
        self, mock_db_session: AsyncMock
    ) -> None:
        """The invite stays redeemable; it just grants nothing until reassigned."""
        await principal_cleanup.remove_role_grants(mock_db_session, role_id=3)

        assert "user_invites" in _updated_tables(mock_db_session)
        assert "user_invites" not in _deleted_tables(mock_db_session)

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db_session: AsyncMock) -> None:
        await principal_cleanup.remove_role_grants(mock_db_session, role_id=3)

        mock_db_session.commit.assert_not_awaited()
