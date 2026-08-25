"""Condition-based notification checks evaluated by the pipeline poller.

Two condition types on a pipeline connection:
    pipeline_idle — the connection (or one named pipeline) has not started a
        run within threshold_minutes, measured via the provider's list_runs.
    data_freshness — max(timestamp_column) of a warehouse table is older than
        threshold_minutes, probed through an org warehouse connection (or the
        built-in marts warehouse when warehouse_connection_id is NULL).

Alerts are state-transition based: one notification when a condition trips and
one on recovery (if notify_on_recovery). Probe errors are recorded on the
condition without flipping its state, so a flaky provider never causes a
false trigger or a false recovery.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_pipeline import DataPipelineConnection
from app.models.pipeline_notification import NotificationCondition
from app.models.warehouse import WarehouseConnection
from app.services import pipeline_providers as providers
from app.services.pipeline_notifications import send_to_groups
from app.services.pipeline_poller import _decrypt_secret, _render
from app.services.sql_identifiers import is_valid_identifier
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

CONDITION_TYPES = ("pipeline_idle", "data_freshness")

_DEFAULT_TEMPLATES = {
    "pipeline_idle": ("⏰ {name}: {scope} has not run in {age} (threshold: {threshold})."),
    "data_freshness": (
        "🕓 {name}: {table} is stale — newest data is {age} old (threshold: {threshold})."
    ),
}


def human_minutes(minutes: float | None) -> str:
    """Format a minute count as a compact human duration."""
    if minutes is None:
        return "unknown"
    m = int(minutes)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _parse_ts(value: object) -> datetime | None:
    """Coerce a driver/provider timestamp (datetime or ISO string) to aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


async def _probe_pipeline_idle(
    db: AsyncSession, cond: NotificationCondition
) -> tuple[datetime | None, str | None]:
    """Return (newest run start, error) for the condition's connection/pipeline."""
    conn = (
        await db.execute(
            select(DataPipelineConnection).where(
                DataPipelineConnection.id == cond.pipeline_connection_id,
                is_true(DataPipelineConnection.is_active),
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        return None, "Pipeline connection not found or inactive"
    provider = providers.get_provider(conn.provider)
    if provider is None or not provider.meta.implemented:
        return None, f"Provider '{conn.provider}' is not implemented"

    # Look back far enough to find a run older than the threshold.
    days = max(2, math.ceil(cond.threshold_minutes / 1440) + 1)
    try:
        result = await provider.list_runs(
            conn.config or {},
            _decrypt_secret(conn),
            limit=25,
            days=days,
            pipeline_name=cond.pipeline_name,
        )
    except Exception as exc:  # noqa: BLE001 — provider errors must not crash the poller
        return None, str(exc)

    newest: datetime | None = None
    for run in result.get("runs", []):
        started = _parse_ts(run.get("started_at"))
        if started and (newest is None or started > newest):
            newest = started
    return newest, None


async def _probe_data_freshness(
    db: AsyncSession, cond: NotificationCondition
) -> tuple[datetime | None, str | None]:
    """Return (max timestamp of the configured table/column, error)."""
    table = cond.table_name or ""
    column = cond.timestamp_column or ""
    schema = cond.schema_name or ""
    if not (is_valid_identifier(table) and is_valid_identifier(column)):
        return None, "Invalid table or column identifier"
    if schema and not is_valid_identifier(schema):
        return None, "Invalid schema identifier"

    if cond.warehouse_connection_id is None:
        # Built-in marts warehouse via the read-only warehouse engine.
        from app.database import warehouse_engine  # noqa: PLC0415

        qualified = f"{schema or 'marts'}.{table}"
        try:
            async with warehouse_engine.connect() as wh_conn:
                result = await wh_conn.execute(text(f"SELECT MAX({column}) FROM {qualified}"))
                return _parse_ts(result.scalar_one_or_none()), None
        except Exception as exc:  # noqa: BLE001 — probe errors are reported, not raised
            return None, str(exc)

    wh = (
        await db.execute(
            select(WarehouseConnection).where(
                WarehouseConnection.id == cond.warehouse_connection_id,
                WarehouseConnection.org_id == cond.org_id,
                is_true(WarehouseConnection.is_active),
            )
        )
    ).scalar_one_or_none()
    if wh is None:
        return None, "Warehouse connection not found or inactive"

    from app.services import warehouse_inspector  # noqa: PLC0415
    from app.services.crypto import decrypt  # noqa: PLC0415

    try:
        password = decrypt(wh.password_encrypted) if wh.password_encrypted else ""
    except Exception:  # noqa: BLE001
        password = ""
    conn_dict = {
        "id": wh.id,
        "name": wh.name,
        "db_type": wh.db_type,
        "host": wh.host,
        "port": wh.port,
        "database_name": wh.database_name,
        "username": wh.username,
        "password": password,
        "schemas": wh.schemas or [],
        "extra_config": wh.extra_config or {},
    }
    qualified = f"{schema}.{table}" if schema else table
    sql = f"SELECT MAX({column}) FROM {qualified}"
    _columns, rows, _total, error = await warehouse_inspector.run_select(conn_dict, sql, 1)
    if error:
        return None, error
    value = rows[0][0] if rows and rows[0] else None
    return _parse_ts(value), None


async def evaluate_condition(db: AsyncSession, cond: NotificationCondition) -> dict[str, Any]:
    """Evaluate a condition without side effects.

    Returns:
        Dict with 'ok' (probe succeeded), 'triggered', 'observed_at',
        'age_minutes', and 'error' keys.
    """
    if cond.condition_type == "pipeline_idle":
        observed, error = await _probe_pipeline_idle(db, cond)
    elif cond.condition_type == "data_freshness":
        observed, error = await _probe_data_freshness(db, cond)
    else:
        observed, error = None, f"Unknown condition type '{cond.condition_type}'"

    if error:
        return {
            "ok": False,
            "triggered": None,
            "observed_at": None,
            "age_minutes": None,
            "error": error,
        }

    age_minutes: float | None = None
    if observed is not None:
        age_minutes = (datetime.now(UTC) - observed).total_seconds() / 60
    # No observation at all (no runs / empty table) counts as triggered.
    triggered = age_minutes is None or age_minutes > cond.threshold_minutes
    return {
        "ok": True,
        "triggered": triggered,
        "observed_at": observed,
        "age_minutes": age_minutes,
        "error": None,
    }


def _build_context(cond: NotificationCondition, result: dict[str, Any]) -> dict[str, Any]:
    scope = cond.pipeline_name or "the connection"
    table = f"{cond.schema_name}.{cond.table_name}" if cond.schema_name else (cond.table_name or "")
    observed = result.get("observed_at")
    return {
        "name": cond.name,
        "scope": scope,
        "pipeline": cond.pipeline_name or "",
        "table": table or "marts",
        "column": cond.timestamp_column or "",
        "age": human_minutes(result.get("age_minutes")),
        "threshold": human_minutes(cond.threshold_minutes),
        "threshold_minutes": cond.threshold_minutes,
        "observed_at": observed.isoformat() if observed else "never",
    }


async def _apply_result(
    db: AsyncSession, cond: NotificationCondition, result: dict[str, Any]
) -> None:
    """Update condition state and send transition notifications."""
    now = datetime.now(UTC)
    cond.last_checked_at = now
    if not result["ok"]:
        # Keep the previous triggered state — a broken probe is not a trigger.
        cond.last_error = result["error"]
        logger.warning(
            "condition_checker.probe_failed", condition_id=cond.id, error=result["error"]
        )
        return

    cond.last_error = None
    cond.last_observed_at = result["observed_at"]
    was_triggered = cond.is_triggered
    now_triggered = bool(result["triggered"])
    cond.is_triggered = now_triggered

    if now_triggered == was_triggered:
        return

    ctx = _build_context(cond, result)
    if now_triggered:
        template = cond.message_template or _DEFAULT_TEMPLATES[cond.condition_type]
        subject = f"Condition alert: {cond.name}"
        message = _render(template, ctx)
    else:
        if not cond.notify_on_recovery:
            return
        subject = f"Condition recovered: {cond.name}"
        message = (
            f"✅ {cond.name}: condition recovered — newest activity {ctx['observed_at']} "
            f"({ctx['age']} old, threshold {ctx['threshold']})."
        )

    try:
        await send_to_groups(
            db,
            cond.org_id,
            cond.group_ids or [],
            subject,
            message,
            source="condition_trigger" if now_triggered else "condition_recovery",
            pipeline_connection_id=cond.pipeline_connection_id,
            condition_id=cond.id,
            pipeline_name=cond.pipeline_name,
        )
        cond.last_notified_at = now
    except Exception as exc:  # noqa: BLE001 — delivery failure must not kill the poller
        logger.warning("condition_checker.send_failed", condition_id=cond.id, error=str(exc))

    # Also feed the per-user preference system (event types 'data_freshness'
    # and 'pipeline_idle') so individual subscriptions work alongside groups.
    from app.services.notifications.dispatcher import dispatch_event  # noqa: PLC0415

    event_type = (
        "data_freshness" if cond.condition_type == "data_freshness" else "pipeline_idle"
    )
    try:
        await dispatch_event(
            event_type=event_type,
            payload={"subject": subject, "message": message, "condition": cond.name},
            org_id=cond.org_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("condition_checker.dispatch_failed", condition_id=cond.id, error=str(exc))


async def check_due_conditions(db: AsyncSession) -> None:
    """Evaluate every enabled condition whose check cadence is due."""
    now = datetime.now(UTC)
    conditions = (
        (
            await db.execute(
                select(NotificationCondition).where(is_true(NotificationCondition.enabled))
            )
        )
        .scalars()
        .all()
    )
    for cond in conditions:
        due = cond.last_checked_at is None or now - cond.last_checked_at >= timedelta(
            minutes=cond.check_frequency_minutes
        )
        if not due:
            continue
        try:
            result = await evaluate_condition(db, cond)
            await _apply_result(db, cond, result)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — one bad condition must not stop the rest
            logger.warning("condition_checker.check_error", condition_id=cond.id, error=str(exc))
            await db.rollback()
