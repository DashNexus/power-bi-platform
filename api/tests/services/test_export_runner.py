"""Tests for the export worker's state transitions and housekeeping.

The bug these exist for: jobs were created as 'running' and nothing ever moved
them off it. Every transition below is one a stuck job would have skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import export_runner
from app.services.export_source import ExportSourceError

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def make_job(**overrides: object) -> SimpleNamespace:
    """Build a stand-in ExportJob with the columns the runner touches."""
    defaults = {
        "id": 1,
        "org_id": 1,
        "user_id": 1,
        "name": "Weekly orders",
        "schedule_id": 7,
        "format": "csv",
        "query_params": {"sql_query": "SELECT 1"},
        "source_kind": "warehouse",
        "warehouse_connection_id": 3,
        "status": "pending",
        "trigger_type": "manual",
        "delivery_method": "download",
        "delivery_config": None,
        "file_path": None,
        "file_name": None,
        "file_size_bytes": None,
        "row_count": None,
        "error_message": None,
        "started_at": None,
        "completed_at": None,
        "expires_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_run_job_marks_completed_and_records_the_result() -> None:
    job = make_job()
    db = make_db()

    with (
        patch.object(
            export_runner,
            "run_report_query",
            AsyncMock(return_value=(["id"], [[1], [2]], False)),
        ),
        patch.object(
            export_runner.export_generator,
            "serialise",
            return_value=(b"id\r\n1\r\n2\r\n", "weekly_orders.csv"),
        ),
        patch.object(
            export_runner.export_generator, "store_result", return_value="/storage/x.csv"
        ),
    ):
        await export_runner.run_job(db, job)

    assert job.status == "completed"
    assert job.row_count == 2
    assert job.file_path == "/storage/x.csv"
    assert job.file_name == "weekly_orders.csv"
    assert job.file_size_bytes == len(b"id\r\n1\r\n2\r\n")
    assert job.error_message is None


@pytest.mark.asyncio
async def test_run_job_sets_started_at_and_running_before_querying() -> None:
    job = make_job()
    db = make_db()
    seen: dict[str, object] = {}

    async def capture(*_args: object, **_kwargs: object) -> tuple:
        seen["status"] = job.status
        seen["started_at"] = job.started_at
        return ["id"], [[1]], False

    with (
        patch.object(export_runner, "run_report_query", capture),
        patch.object(
            export_runner.export_generator, "serialise", return_value=(b"x", "x.csv")
        ),
        patch.object(export_runner.export_generator, "store_result", return_value="/p"),
    ):
        await export_runner.run_job(db, job)

    assert seen["status"] == "running"
    assert seen["started_at"] is not None


@pytest.mark.asyncio
async def test_run_job_sets_expiry_thirty_days_out() -> None:
    job = make_job()
    db = make_db()

    with (
        patch.object(
            export_runner, "run_report_query", AsyncMock(return_value=(["id"], [[1]], False))
        ),
        patch.object(
            export_runner.export_generator, "serialise", return_value=(b"x", "x.csv")
        ),
        patch.object(export_runner.export_generator, "store_result", return_value="/p"),
    ):
        await export_runner.run_job(db, job)

    assert job.expires_at is not None
    window = job.expires_at - job.completed_at
    assert window == timedelta(days=export_runner.RESULT_RETENTION_DAYS)


@pytest.mark.asyncio
async def test_run_job_records_a_source_failure_without_raising() -> None:
    job = make_job()
    db = make_db()

    with patch.object(
        export_runner,
        "run_report_query",
        AsyncMock(side_effect=ExportSourceError("Invalid object name 'nope'.")),
    ):
        await export_runner.run_job(db, job)

    assert job.status == "failed"
    assert job.completed_at is not None
    assert "Invalid object name" in job.error_message


@pytest.mark.asyncio
async def test_run_job_fails_a_job_with_no_query_rather_than_hanging() -> None:
    job = make_job(query_params={})
    db = make_db()

    await export_runner.run_job(db, job)

    assert job.status == "failed"
    assert "no query" in job.error_message


@pytest.mark.asyncio
async def test_run_job_notes_truncation_on_an_otherwise_successful_run() -> None:
    job = make_job()
    db = make_db()

    with (
        patch.object(
            export_runner, "run_report_query", AsyncMock(return_value=(["id"], [[1]], True))
        ),
        patch.object(
            export_runner.export_generator, "serialise", return_value=(b"x", "x.csv")
        ),
        patch.object(export_runner.export_generator, "store_result", return_value="/p"),
    ):
        await export_runner.run_job(db, job)

    assert job.status == "completed"
    assert "returned more" in job.error_message


@pytest.mark.asyncio
async def test_run_job_keeps_the_file_when_delivery_fails() -> None:
    job = make_job(delivery_method="email", delivery_config={"recipients": ["a@b.c"]})
    db = make_db()

    with (
        patch.object(
            export_runner, "run_report_query", AsyncMock(return_value=(["id"], [[1]], False))
        ),
        patch.object(
            export_runner.export_generator, "serialise", return_value=(b"x", "x.csv")
        ),
        patch.object(export_runner.export_generator, "store_result", return_value="/p"),
        patch(
            "app.services.export_delivery.deliver_export",
            AsyncMock(side_effect=RuntimeError("SMTP refused")),
        ),
    ):
        await export_runner.run_job(db, job)

    assert job.status == "completed"
    assert job.file_path == "/p"
    assert "delivery failed" in job.error_message


@pytest.mark.asyncio
async def test_reap_stuck_jobs_fails_a_run_past_the_timeout() -> None:
    stuck = make_job(status="running", started_at=NOW - timedelta(hours=2))
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[stuck])))
    )

    reaped = await export_runner.reap_stuck_jobs(db, NOW)

    assert reaped == 1
    assert stuck.status == "failed"
    assert "Timed out" in stuck.error_message
    assert stuck.completed_at == NOW


@pytest.mark.asyncio
async def test_reap_stuck_jobs_commits_nothing_when_none_are_stuck() -> None:
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )

    reaped = await export_runner.reap_stuck_jobs(db, NOW)

    assert reaped == 0
    db.commit.assert_not_awaited()


def make_schedule(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": 7,
        "org_id": 1,
        "user_id": 1,
        "name": "Weekly orders",
        "format": "csv",
        "sql_query": "SELECT 1",
        "source_kind": "warehouse",
        "warehouse_connection_id": 3,
        "cron_expression": "0 12 * * *",
        "is_active": True,
        "last_run_at": None,
        "delivery_method": "download",
        "delivery_config": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_enqueue_due_schedules_creates_a_pending_job_and_stamps_last_run() -> None:
    schedule = make_schedule()
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[schedule])))
    )

    count = await export_runner.enqueue_due_schedules(db, NOW)

    assert count == 1
    assert schedule.last_run_at == NOW
    job = db.add.call_args[0][0]
    assert job.status == "pending"
    assert job.trigger_type == "schedule"
    assert job.schedule_id == 7
    assert job.source_kind == "warehouse"
    assert job.query_params == {"sql_query": "SELECT 1"}


@pytest.mark.asyncio
async def test_enqueue_due_schedules_skips_a_schedule_that_is_not_due() -> None:
    schedule = make_schedule(cron_expression="0 3 * * *")
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[schedule])))
    )

    assert await export_runner.enqueue_due_schedules(db, NOW) == 0
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_due_schedules_skips_a_malformed_cron_without_failing_the_sweep() -> None:
    bad = make_schedule(id=1, cron_expression="not a cron")
    good = make_schedule(id=2)
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[bad, good])))
    )

    assert await export_runner.enqueue_due_schedules(db, NOW) == 1


@pytest.mark.asyncio
async def test_enqueue_due_schedules_tolerates_a_naive_last_run_at() -> None:
    # SQL Server returns naive datetimes through some driver paths; comparing
    # one to an aware `now` would raise TypeError inside the tick.
    schedule = make_schedule(last_run_at=(NOW - timedelta(days=1)).replace(tzinfo=None))
    db = make_db()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[schedule])))
    )

    assert await export_runner.enqueue_due_schedules(db, NOW) == 1


@pytest.mark.asyncio
async def test_purge_expired_results_deletes_the_file_before_the_row() -> None:
    expired = make_job(id=5, expires_at=NOW - timedelta(days=1), file_path="/storage/old.csv")
    db = make_db()
    db.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[expired])))),
        MagicMock(rowcount=0),
        MagicMock(rowcount=0),
    ]

    with patch.object(export_runner.export_generator, "delete_result") as delete_result:
        purged = await export_runner.purge_expired_results(db, NOW)

    assert purged == 1
    delete_result.assert_called_once_with("/storage/old.csv")


@pytest.mark.asyncio
async def test_purge_expired_results_keeps_a_result_inside_the_window() -> None:
    db = make_db()
    db.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(rowcount=0),
    ]

    with patch.object(export_runner.export_generator, "delete_result") as delete_result:
        assert await export_runner.purge_expired_results(db, NOW) == 0

    delete_result.assert_not_called()
