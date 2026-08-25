"""Tests for the exports router: report access control and run lifecycle.

Reports read live databases, so most of what matters here is who is allowed to
point one at what — and that a run is queued rather than declared finished.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, select

from app.middleware.auth import CurrentUser
from app.models.audit import AuditLog
from app.models.export import ExportJob
from app.routers import exports
from app.schemas.export import ExportScheduleRequest


@pytest.fixture()
def mock_analyst_user() -> CurrentUser:
    return CurrentUser(user_id=2, org_id=1, role="analyst", email="analyst@example.com")


def make_request(**overrides: object) -> ExportScheduleRequest:
    defaults = {
        "name": "Weekly orders",
        "format": "csv",
        "cron_expression": "0 6 * * 1",
        "sql_query": "SELECT * FROM marts.orders",
        "source_kind": "warehouse",
        "warehouse_connection_id": 3,
    }
    defaults.update(overrides)
    return ExportScheduleRequest(**defaults)


def make_connection(**overrides: object) -> SimpleNamespace:
    defaults = {"id": 3, "org_id": 1, "name": "Analytics", "is_active": True}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def result_with(value: object) -> MagicMock:
    """Shape a db.execute result whose scalar_one_or_none() returns value."""
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


class TestReportSourceValidation:
    """_validate_report_source decides what a report may point at."""

    @pytest.mark.asyncio
    async def test_warehouse_source_allowed_with_query_access(
        self, mock_analyst_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(make_connection())

        with patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)):
            await exports._validate_report_source(db, make_request(), mock_analyst_user)

    @pytest.mark.asyncio
    async def test_warehouse_source_denied_without_query_access(
        self, mock_analyst_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(make_connection())

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=False)),
            pytest.raises(HTTPException) as exc,
        ):
            await exports._validate_report_source(db, make_request(), mock_analyst_user)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_bypasses_the_query_access_check(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(make_connection())

        # user_can_query_connection returns True for an admin on its own; this
        # asserts the router routes admins through it rather than short-cutting.
        with patch.object(
            exports, "user_can_query_connection", AsyncMock(return_value=True)
        ) as check:
            await exports._validate_report_source(db, make_request(), mock_admin_user)

        check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cross_org_connection_is_404(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(None)

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(db, make_request(), mock_admin_user)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_warehouse_source_requires_a_connection_to_be_chosen(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(
                db, make_request(warehouse_connection_id=None), mock_admin_user
            )

        assert exc.value.status_code == 400
        assert "warehouse connection" in exc.value.detail

    @pytest.mark.asyncio
    async def test_operations_source_is_admin_only(self, mock_analyst_user: CurrentUser) -> None:
        db = AsyncMock()
        request = make_request(source_kind="operations", warehouse_connection_id=None)

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(db, request, mock_analyst_user)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_operations_source_allowed_for_an_admin(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        request = make_request(
            source_kind="operations",
            warehouse_connection_id=None,
            sql_query="SELECT id, name FROM orgs",
        )

        await exports._validate_report_source(db, request, mock_admin_user)

    @pytest.mark.asyncio
    async def test_operations_source_refuses_credential_tables(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        request = make_request(
            source_kind="operations",
            warehouse_connection_id=None,
            sql_query="SELECT email, hashed_password FROM users",
        )

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(db, request, mock_admin_user)

        assert exc.value.status_code == 400
        assert "users" in exc.value.detail

    @pytest.mark.asyncio
    async def test_write_sql_is_rejected(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(
                db, make_request(sql_query="DELETE FROM marts.orders"), mock_admin_user
            )

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_malformed_cron_is_rejected_with_the_field_named(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(
                db, make_request(cron_expression="0 99 * * *"), mock_admin_user
            )

        assert exc.value.status_code == 400
        assert "hour" in exc.value.detail

    @pytest.mark.asyncio
    async def test_unknown_source_kind_is_rejected(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await exports._validate_report_source(
                db, make_request(source_kind="somewhere_else"), mock_admin_user
            )

        assert exc.value.status_code == 400


class TestOnDemandReports:
    """A report with no cron expression runs only when asked."""

    def test_blank_cron_is_normalised_to_none(self) -> None:
        assert make_request(cron_expression="   ").cron_expression is None

    def test_omitted_cron_is_none(self) -> None:
        request = ExportScheduleRequest(name="Ad hoc", format="csv", sql_query="SELECT 1")

        assert request.cron_expression is None

    @pytest.mark.asyncio
    async def test_a_report_with_no_cron_passes_validation(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(make_connection())

        with patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)):
            await exports._validate_report_source(
                db, make_request(cron_expression=None), mock_admin_user
            )


class TestRunReportNow:
    """Run now queues work; it never reports a result it does not have."""

    @pytest.mark.asyncio
    async def test_queues_a_pending_job_carrying_the_report_source(
        self, mock_admin_user: CurrentUser
    ) -> None:
        report = SimpleNamespace(
            id=7,
            org_id=1,
            user_id=1,
            name="Weekly orders",
            format="csv",
            sql_query="SELECT 1",
            source_kind="warehouse",
            warehouse_connection_id=3,
            delivery_method="download",
            delivery_config=None,
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            result_with(report),
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),
        ]

        with patch.object(exports.ExportJobResponse, "model_validate", lambda job: job):
            await exports.run_report_now(7, current_user=mock_admin_user, db=db)

        job = db.add.call_args_list[0][0][0]
        assert job.status == "pending"
        assert job.trigger_type == "manual"
        assert job.schedule_id == 7
        assert job.source_kind == "warehouse"
        assert job.warehouse_connection_id == 3
        assert job.name == "Weekly orders"

    @pytest.mark.asyncio
    async def test_refuses_a_second_run_while_one_is_in_flight(
        self, mock_admin_user: CurrentUser
    ) -> None:
        report = SimpleNamespace(
            id=7, org_id=1, user_id=1, name="R", format="csv", sql_query="SELECT 1",
            source_kind="warehouse", warehouse_connection_id=3,
            delivery_method="download", delivery_config=None,
        )
        in_flight = SimpleNamespace(id=99, status="running")
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            result_with(report),
            MagicMock(
                scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=in_flight)))
            ),
        ]

        with pytest.raises(HTTPException) as exc:
            await exports.run_report_now(7, current_user=mock_admin_user, db=db)

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_missing_report_is_404(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(None)

        with pytest.raises(HTTPException) as exc:
            await exports.run_report_now(999, current_user=mock_admin_user, db=db)

        assert exc.value.status_code == 404


class TestDownload:
    """Downloading distinguishes not-ready from expired."""

    @pytest.mark.asyncio
    async def test_a_running_job_is_409_not_404(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(
            SimpleNamespace(id=1, status="running", file_path=None)
        )

        with pytest.raises(HTTPException) as exc:
            await exports.download_export(1, current_user=mock_admin_user, db=db)

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_a_purged_result_is_410_not_404(self, mock_admin_user: CurrentUser) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(
            SimpleNamespace(id=1, status="completed", file_path=None)
        )

        with pytest.raises(HTTPException) as exc:
            await exports.download_export(1, current_user=mock_admin_user, db=db)

        assert exc.value.status_code == 410
        assert "retention" in exc.value.detail

    @pytest.mark.asyncio
    async def test_a_completed_run_returns_its_real_name_and_size(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = AsyncMock()
        db.execute.return_value = result_with(
            SimpleNamespace(
                id=1,
                status="completed",
                format="csv",
                file_path="/storage/exports/job_1/weekly.csv",
                file_name="weekly.csv",
                file_size_bytes=2048,
            )
        )

        response = await exports.download_export(1, current_user=mock_admin_user, db=db)

        assert response.file_name == "weekly.csv"
        assert response.file_size_bytes == 2048


class TestRemovedEndpoints:
    """Endpoints deleted because they were unguarded or unrunnable.

    Asserted by absence: both had their own access-control path, and the way a
    second path becomes a hole is by being re-added without the checks.
    """

    def test_there_is_no_unguarded_job_creation_endpoint(self) -> None:
        # POST /exports/jobs queued arbitrary SQL against any source without
        # _validate_report_source, so a viewer could read the operations
        # database. A one-off export is a report plus a run.
        assert not hasattr(exports, "create_job")
        routes = {(r.path, m) for r in exports.router.routes for m in r.methods}
        assert ("/jobs", "POST") not in routes

    def test_there_are_no_query_less_schedule_endpoints(self) -> None:
        # An ExportSchedule with no sql_query records when and where to deliver
        # but not what, so nothing could ever run one.
        assert not hasattr(exports, "create_schedule")
        paths = {r.path for r in exports.router.routes}
        assert "/schedules" not in paths
        assert "/schedules/{sched_id}" not in paths

    def test_the_report_endpoints_that_replace_them_are_present(self) -> None:
        paths = {r.path for r in exports.router.routes}

        assert {"/reports", "/reports/{report_id}", "/reports/{report_id}/run"} <= paths


class TestRunLogFilters:
    """_apply_run_filters narrows the run log for the search box.

    Filtering is server-side because the run log is capped by a limit: a browser
    filtering the rows it already has would report "no matches" for a run that
    is simply further down the table.
    """

    @staticmethod
    def _filtered(**kwargs: object) -> Select[tuple[ExportJob]]:
        defaults = {"search": None, "status": None, "trigger_type": None}
        defaults.update(kwargs)
        return exports._apply_run_filters(select(ExportJob), **defaults)

    def test_no_filters_leaves_the_query_untouched(self) -> None:
        stmt = self._filtered()

        assert stmt.whereclause is None

    def test_blank_search_is_not_a_filter(self) -> None:
        # An empty search box must not become `LIKE '%%'` — every row matches,
        # but the query stops being the cheap unfiltered one.
        stmt = self._filtered(search="   ")

        assert stmt.whereclause is None

    def test_search_covers_name_format_and_error(self) -> None:
        stmt = self._filtered(search="timeout")
        sql = str(stmt.whereclause)

        assert "export_jobs.name" in sql
        assert "export_jobs.format" in sql
        assert "export_jobs.error_message" in sql

    def test_search_wraps_the_term_in_wildcards(self) -> None:
        stmt = self._filtered(search="  orders  ")

        assert set(stmt.compile().params.values()) == {"%orders%"}

    def test_search_escapes_a_literal_percent(self) -> None:
        # Without escaping, searching for a run named "100% sample" matches
        # every row in the log.
        stmt = self._filtered(search="100%")

        assert set(stmt.compile().params.values()) == {"%100\\%%"}
        assert "ESCAPE" in str(stmt.whereclause)

    def test_search_escapes_a_literal_underscore(self) -> None:
        stmt = self._filtered(search="a_b")

        assert set(stmt.compile().params.values()) == {"%a\\_b%"}

    @pytest.mark.parametrize("status", exports._RUN_STATUSES)
    def test_every_offered_status_is_accepted(self, status: str) -> None:
        stmt = self._filtered(status=status)

        assert stmt.compile().params["status_1"] == status

    def test_an_unknown_status_is_refused_rather_than_matching_nothing(self) -> None:
        # Returning an empty list would be indistinguishable from a real query
        # with no results, so a typo would read as "this report never ran".
        with pytest.raises(HTTPException) as exc:
            self._filtered(status="cancelled")

        assert exc.value.status_code == 400
        assert "status must be one of" in exc.value.detail

    @pytest.mark.parametrize("trigger", exports._TRIGGER_TYPES)
    def test_every_offered_trigger_is_accepted(self, trigger: str) -> None:
        stmt = self._filtered(trigger_type=trigger)

        assert stmt.compile().params["trigger_type_1"] == trigger

    def test_an_unknown_trigger_is_refused(self) -> None:
        with pytest.raises(HTTPException) as exc:
            self._filtered(trigger_type="cron")

        assert exc.value.status_code == 400

    def test_cancelled_is_not_offered_because_no_run_carries_it(self) -> None:
        # export_runner.cancel_job marks a cancelled run "failed" with
        # "Cancelled." as its message. Offering "cancelled" as a filter would be
        # an option that can only ever return nothing.
        assert "cancelled" not in exports._RUN_STATUSES

    def test_filters_combine_rather_than_replace_the_scope(self) -> None:
        # The org and user predicates are what keep one person's runs out of
        # another's; a filter must narrow them, never stand in for them.
        base = select(ExportJob).where(ExportJob.org_id == 1, ExportJob.user_id == 2)

        stmt = exports._apply_run_filters(
            base, search="orders", status="failed", trigger_type="manual"
        )

        sql = str(stmt.whereclause)
        assert "export_jobs.org_id" in sql
        assert "export_jobs.user_id" in sql
        assert "export_jobs.status" in sql


class TestReportChangeLedger:
    """Report mutations are recorded in the change ledger, not only the audit log.

    The audit log says a report changed; the ledger stores the before/after that
    makes the change revertible and puts it on /admin/changes.
    """

    @staticmethod
    def _session(order: list[str] | None = None) -> AsyncMock:
        """Return a session mock that stamps primary keys on flush, as a real one does.

        Without this the report keeps id=None and the handler fails validating
        its own response — after the call under test, so the failure points at
        the wrong place.
        """
        db = AsyncMock()
        added: list[object] = []
        # MagicMock, not AsyncMock: Session.add is synchronous, and an async
        # stand-in returns a coroutine nobody awaits.
        db.add = MagicMock(side_effect=added.append)

        async def flush() -> None:
            if order is not None:
                order.append("flush")
            for obj in added:
                if getattr(obj, "id", None) is None:
                    obj.id = 42

        db.flush = AsyncMock(side_effect=flush)
        return db

    @pytest.mark.asyncio
    async def test_creating_a_report_records_a_ledger_create(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = self._session()
        db.execute = AsyncMock(return_value=result_with(make_connection()))

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)),
            patch.object(exports.ledger, "log_create", AsyncMock()) as log_create,
        ):
            await exports.create_report(make_request(), mock_admin_user, db)

        assert log_create.await_args.kwargs["resource_type"] == "report"
        assert log_create.await_args.kwargs["resource_name"] == "Weekly orders"

    @pytest.mark.asyncio
    async def test_the_ledger_entry_is_written_after_the_row_has_an_id(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # log_create snapshots the object it is given. Called before the flush,
        # it records resource_id=None — an entry nothing can tie to its report,
        # and one that cannot be reverted.
        order: list[str] = []
        db = self._session(order)
        db.execute = AsyncMock(return_value=result_with(make_connection()))

        async def note_create(*_args: object, **kwargs: object) -> None:
            order.append(f"log_create id={kwargs['obj'].id}")

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)),
            patch.object(exports.ledger, "log_create", AsyncMock(side_effect=note_create)),
        ):
            await exports.create_report(make_request(), mock_admin_user, db)

        assert order == ["flush", "log_create id=42"]

    @pytest.mark.asyncio
    async def test_the_audit_entry_names_the_report_it_describes(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # It used to be added before the flush with neither resource_id nor
        # resource_name, so /admin/audit showed "report.created" against nothing.
        db = self._session()
        db.execute = AsyncMock(return_value=result_with(make_connection()))

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)),
            patch.object(exports.ledger, "log_create", AsyncMock()),
        ):
            await exports.create_report(make_request(), mock_admin_user, db)

        audit = next(
            call.args[0]
            for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        )
        assert audit.resource_id == 42
        assert audit.resource_name == "Weekly orders"

    @pytest.mark.asyncio
    async def test_updating_a_report_records_the_state_it_had_before(
        self, mock_admin_user: CurrentUser
    ) -> None:
        report = SimpleNamespace(
            id=7, org_id=1, user_id=1, name="Old name", format="csv",
            cron_expression=None, sql_query="SELECT 1", source_kind="warehouse",
            warehouse_connection_id=3, delivery_method="download", delivery_config=None,
            query_params={}, is_active=True, last_run_at=None,
        )
        db = self._session()
        db.execute = AsyncMock(side_effect=[result_with(report), result_with(make_connection())])

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)),
            patch.object(
                exports.ledger, "serialize_row", MagicMock(return_value={"name": "Old name"})
            ),
            patch.object(exports.ledger, "log_update", AsyncMock()) as log_update,
        ):
            await exports.update_report(7, make_request(name="New name"), mock_admin_user, db)

        assert log_update.await_args.kwargs["before"] == {"name": "Old name"}
        assert log_update.await_args.kwargs["resource_name"] == "New name"

    @pytest.mark.asyncio
    async def test_the_update_snapshot_is_taken_before_the_fields_change(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # A snapshot taken after the assignments records the new values as the
        # old ones, which makes the revert a no-op that reports success.
        report = SimpleNamespace(
            id=7, org_id=1, user_id=1, name="Old name", format="csv",
            cron_expression=None, sql_query="SELECT 1", source_kind="warehouse",
            warehouse_connection_id=3, delivery_method="download", delivery_config=None,
            query_params={}, is_active=True, last_run_at=None,
        )
        db = self._session()
        db.execute = AsyncMock(side_effect=[result_with(report), result_with(make_connection())])
        captured: list[str] = []

        with (
            patch.object(exports, "user_can_query_connection", AsyncMock(return_value=True)),
            patch.object(
                exports.ledger,
                "serialize_row",
                MagicMock(side_effect=lambda obj: captured.append(obj.name) or {}),
            ),
            patch.object(exports.ledger, "log_update", AsyncMock()),
        ):
            await exports.update_report(7, make_request(name="New name"), mock_admin_user, db)

        assert captured[0] == "Old name"

    @pytest.mark.asyncio
    async def test_deleting_a_report_snapshots_it_before_the_row_goes(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # log_delete serialises the object it is handed, so it has to run while
        # the row is intact — after db.delete there is nothing left to record.
        report = SimpleNamespace(id=7, org_id=1, user_id=1, name="Weekly orders")
        db = self._session()
        db.execute = AsyncMock(return_value=result_with(report))
        order: list[str] = []
        db.delete = AsyncMock(side_effect=lambda _: order.append("delete"))

        with (
            patch.object(exports, "clear_schedule_links", AsyncMock()),
            patch.object(
                exports.ledger,
                "log_delete",
                AsyncMock(side_effect=lambda *a, **k: order.append("log_delete")),
            ),
        ):
            await exports.delete_report(7, mock_admin_user, db)

        assert order == ["log_delete", "delete"]
