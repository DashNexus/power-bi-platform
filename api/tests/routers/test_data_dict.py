"""Unit tests for data dictionary endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    entry_id: int = 1,
    schema_name: str = "public",
    table_name: str = "orders",
    column_name: str | None = "id",
    description: str | None = None,
    is_pii: bool = False,
    is_pk: bool = False,
    fk_table: str | None = None,
    fk_schema: str | None = None,
    fk_column: str | None = None,
    relationship_type: str | None = None,
    tags: list | None = None,
    ai_generated: bool = False,
    org_id: int = 1,
    warehouse_connection_id: int = 1,
) -> MagicMock:
    entry = MagicMock()
    entry.id = entry_id
    entry.org_id = org_id
    entry.warehouse_connection_id = warehouse_connection_id
    entry.schema_name = schema_name
    entry.table_name = table_name
    entry.column_name = column_name
    entry.description = description
    entry.data_type = "int"
    entry.is_pii = is_pii
    entry.is_pk = is_pk
    entry.fk_schema = fk_schema
    entry.fk_table = fk_table
    entry.fk_column = fk_column
    entry.relationship_type = relationship_type
    entry.tags = tags or []
    entry.ai_generated = ai_generated
    entry.created_at = MagicMock()
    entry.created_at.isoformat.return_value = "2025-01-01T00:00:00"
    entry.updated_at = MagicMock()
    entry.updated_at.isoformat.return_value = "2025-01-01T00:00:00"
    return entry


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars_result(items: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# list_entries (GET /data-dictionary)
# ---------------------------------------------------------------------------


class TestListEntries:
    @pytest.mark.asyncio
    async def test_returns_entries_for_table(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Returns serialised entries filtered by warehouse and table."""
        from app.routers.data_dict import list_entries

        entry = _make_entry(entry_id=1, table_name="orders")
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([entry]))

        result = await list_entries(
            warehouse_connection_id=1,
            schema_name="public",
            table_name="orders",
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["table_name"] == "orders"


# ---------------------------------------------------------------------------
# create_or_upsert_entry (POST /data-dictionary)
# ---------------------------------------------------------------------------


class TestCreateOrUpsertEntry:
    @pytest.mark.asyncio
    async def test_creates_new_entry_and_audits(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Creates a new entry when none exists, commits, and fires audit_action."""
        from app.routers.data_dict import DataDictEntryCreate, create_or_upsert_entry

        data = DataDictEntryCreate(
            warehouse_connection_id=1,
            schema_name="public",
            table_name="orders",
            column_name="status",
            description="Order status",
        )
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))
        mock_db_session.flush = AsyncMock()
        mock_db_session.refresh = AsyncMock(return_value=None)

        # Patch the serializer (not the ORM model — the endpoint passes the model
        # to select(), which rejects a MagicMock) so serialization of the freshly
        # built, unpersisted entry doesn't touch server-populated timestamps.
        with patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit, \
             patch("app.routers.data_dict._serialize_entry", return_value={}):
            mock_audit.return_value = None
            await create_or_upsert_entry(
                data=data, current_user=mock_admin_user, db=mock_db_session
            )

        mock_db_session.commit.assert_awaited_once()
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert "created" in call_kwargs["action"]

    @pytest.mark.asyncio
    async def test_updates_existing_entry(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Updates description on an existing entry and fires an 'updated' audit."""
        from app.routers.data_dict import DataDictEntryCreate, create_or_upsert_entry

        existing = _make_entry(entry_id=2, column_name="amount", description="Old desc")
        data = DataDictEntryCreate(
            warehouse_connection_id=1,
            schema_name="public",
            table_name="orders",
            column_name="amount",
            description="New desc",
        )
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(existing))
        mock_db_session.refresh = AsyncMock(return_value=None)

        with patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit:
            mock_audit.return_value = None
            await create_or_upsert_entry(
                data=data, current_user=mock_admin_user, db=mock_db_session
            )

        assert existing.description == "New desc"
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert "updated" in call_kwargs["action"]


# ---------------------------------------------------------------------------
# update_entry (PUT /data-dictionary/{entry_id})
# ---------------------------------------------------------------------------


class TestUpdateEntry:
    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Raises HTTP 404 when the entry does not exist."""
        from fastapi import HTTPException

        from app.routers.data_dict import DataDictEntryUpdate, update_entry

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await update_entry(
                entry_id=999,
                data=DataDictEntryUpdate(description="desc"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_updates_description_and_logs_change(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Updates description, writes changelog, adds audit log, and commits."""
        from app.routers.data_dict import DataDictEntryUpdate, update_entry

        entry = _make_entry(entry_id=3, description="Old")
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(entry))
        mock_db_session.flush = AsyncMock()
        mock_db_session.refresh = AsyncMock(return_value=None)

        with patch("app.routers.data_dict._write_changelog", new_callable=AsyncMock) as mock_log, \
             patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit:
            mock_log.return_value = None
            mock_audit.return_value = None
            await update_entry(
                entry_id=3,
                data=DataDictEntryUpdate(description="New"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert entry.description == "New"
        mock_log.assert_awaited_once()
        mock_audit.assert_awaited_once()
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_audit_when_no_changes(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Does not write an audit entry when nothing actually changed."""
        from app.routers.data_dict import DataDictEntryUpdate, update_entry

        entry = _make_entry(entry_id=4, description="Same")
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(entry))
        mock_db_session.refresh = AsyncMock(return_value=None)

        with patch("app.routers.data_dict._write_changelog", new_callable=AsyncMock) as mock_log, \
             patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit:
            mock_log.return_value = None
            mock_audit.return_value = None
            await update_entry(
                entry_id=4,
                data=DataDictEntryUpdate(description="Same"),  # identical value
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        mock_log.assert_not_called()
        mock_audit.assert_not_called()


# ---------------------------------------------------------------------------
# delete_entry (DELETE /data-dictionary/{entry_id})
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        from fastapi import HTTPException

        from app.routers.data_dict import delete_entry

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await delete_entry(entry_id=999, current_user=mock_admin_user, db=mock_db_session)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deletes_entry_and_audits(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Deleting an entry fires audit_action and commits."""
        from app.routers.data_dict import delete_entry

        entry = _make_entry(entry_id=6)
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(entry))
        mock_db_session.delete = AsyncMock()

        with patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit:
            mock_audit.return_value = None
            await delete_entry(entry_id=6, current_user=mock_admin_user, db=mock_db_session)

        mock_db_session.delete.assert_awaited_once_with(entry)
        mock_db_session.commit.assert_awaited_once()
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "data_dict.entry_deleted"


# ---------------------------------------------------------------------------
# add_exclusion (POST /data-dictionary/exclusions)
# ---------------------------------------------------------------------------


class TestAddExclusion:
    @pytest.mark.asyncio
    async def test_returns_existing_exclusion_without_insert(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Returns the existing exclusion row idempotently without writing audit."""
        from app.routers.data_dict import ExclusionCreate, add_exclusion

        exc_row = MagicMock()
        exc_row.id = 1
        exc_row.warehouse_connection_id = 1
        exc_row.schema_name = "staging"
        exc_row.table_name = None
        exc_row.created_at = MagicMock()
        exc_row.created_at.isoformat.return_value = "2025-01-01T00:00:00"

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(exc_row))

        with patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit:
            result = await add_exclusion(
                data=ExclusionCreate(warehouse_connection_id=1, schema_name="staging"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        # Returns existing row — no insert, no audit
        assert result["schema_name"] == "staging"
        mock_db_session.commit.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_new_exclusion_and_audits(
        self,
        mock_admin_user: CurrentUser,
        mock_db_session: AsyncMock,
    ) -> None:
        """Creates exclusion and fires audit when none exists."""
        from app.routers.data_dict import ExclusionCreate, add_exclusion

        # First execute → no existing row; second (IntegrityError path) not needed
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))
        mock_db_session.refresh = AsyncMock(return_value=None)

        # Patch the serializer (not the ORM model — the endpoint passes it to
        # select(), which rejects a MagicMock) to avoid touching timestamps on
        # the freshly built, unpersisted exclusion.
        with patch("app.services.audit.audit_action", new_callable=AsyncMock) as mock_audit, \
             patch("app.routers.data_dict._serialize_exclusion", return_value={}):
            mock_audit.return_value = None
            await add_exclusion(
                data=ExclusionCreate(
                    warehouse_connection_id=1,
                    schema_name="raw",
                    table_name="temp_load",
                ),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        mock_db_session.commit.assert_awaited_once()
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "data_dict.exclusion_added"


# ---------------------------------------------------------------------------
# _parse_fk_ref (pure function)
# ---------------------------------------------------------------------------


class TestParseFkRef:
    def test_three_part_ref(self) -> None:
        from app.routers.data_dict import _parse_fk_ref

        schema, table, col = _parse_fk_ref("public.orders.id")
        assert schema == "public"
        assert table == "orders"
        assert col == "id"

    def test_two_part_ref_has_no_schema(self) -> None:
        from app.routers.data_dict import _parse_fk_ref

        schema, table, col = _parse_fk_ref("orders.id")
        assert schema is None
        assert table == "orders"
        assert col == "id"

    def test_single_part_returns_all_none(self) -> None:
        from app.routers.data_dict import _parse_fk_ref

        schema, table, col = _parse_fk_ref("orders")
        assert schema is None
        assert table is None
        assert col is None


# ---------------------------------------------------------------------------
# get/set_dict_permissions (data dictionary sharing)
# ---------------------------------------------------------------------------


class TestGetDictPermissions:
    @pytest.mark.asyncio
    async def test_raises_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """The connection-existence guard returns 404 for an unknown connection."""
        from fastapi import HTTPException

        from app.routers.data_dict import get_dict_permissions

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await get_dict_permissions(
                connection_id=999, current_user=mock_admin_user, db=mock_db_session
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_role_ids_for_existing_connection(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_dict import get_dict_permissions

        perm1 = MagicMock()
        perm1.role_id = 5
        perm2 = MagicMock()
        perm2.role_id = None  # legacy user-scoped grant — excluded
        perm3 = MagicMock()
        perm3.role_id = 8

        # execute #1 connection-exists check; execute #2 grant rows.
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), _scalars_result([perm1, perm2, perm3])]
        )

        result = await get_dict_permissions(
            connection_id=1, current_user=mock_admin_user, db=mock_db_session
        )

        assert result == {"role_ids": [5, 8]}


class TestSetDictPermissions:
    @pytest.mark.asyncio
    async def test_raises_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.data_dict import set_dict_permissions

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await set_dict_permissions(
                connection_id=999,
                data={"role_ids": [1]},
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404
        mock_db_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replaces_grants_and_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """Deletes existing grants, inserts one row per role, commits once."""
        from app.routers.data_dict import set_dict_permissions

        # execute #1 exists-check; execute #2 the DELETE.
        mock_db_session.execute = AsyncMock(side_effect=[_scalar_result(1), MagicMock()])

        result = await set_dict_permissions(
            connection_id=1,
            data={"role_ids": [3, 4]},
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        assert mock_db_session.add.call_count == 2
        mock_db_session.commit.assert_awaited_once()
        assert "2 grants" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_list_clears_grants(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_dict import set_dict_permissions

        mock_db_session.execute = AsyncMock(side_effect=[_scalar_result(1), MagicMock()])

        result = await set_dict_permissions(
            connection_id=1,
            data={"role_ids": []},
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        mock_db_session.add.assert_not_called()
        assert "0 grants" in result["message"]
