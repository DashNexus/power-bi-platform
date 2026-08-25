"""Pipeline notification configuration: notification groups + per-connection config.

Admin-only. Notification groups are reusable destination sets; each pipeline
connection has one notification config (enable, success/failure toggles,
message templates, poll frequency, target groups, per-pipeline overrides).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user, require_role
from app.models.data_pipeline import DataPipelineConnection
from app.models.pipeline_notification import (
    NotificationCondition,
    NotificationDelivery,
    NotificationGroup,
    PipelineNotificationConfig,
)
from app.models.user import User
from app.models.warehouse import WarehouseConnection
from app.services.sql_identifiers import is_valid_identifier
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

_admin_dep = require_role("admin", "superadmin")

_MIN_POLL_MINUTES = 10
_MAX_POLL_MINUTES = 24 * 60


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NotificationGroupIn(BaseModel):
    """Create/update payload for a notification group."""

    name: str
    channels: dict[str, Any] = {}


class NotificationConfigIn(BaseModel):
    """Per-connection notification config payload."""

    enabled: bool = False
    notify_on_success: bool = False
    notify_on_failure: bool = True
    success_message: str
    failure_message: str
    poll_frequency_minutes: int = 60
    success_group_ids: list[int] = []
    failure_group_ids: list[int] = []
    # {name: {notify_on_success?, notify_on_failure?, success_message?, failure_message?}}
    pipeline_overrides: dict[str, dict[str, Any]] = {}
    # Suppression. 0 disables the throttle; a NULL quiet-hours bound disables it.
    min_interval_minutes: int = Field(default=0, ge=0, le=60 * 24)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_tz: str = "UTC"
    quiet_hours_include_failures: bool = False


class TestNotificationIn(BaseModel):
    """Test-send payload.

    Defaults reproduce the original behaviour (a fixed message to every group on
    the config) so existing callers keep working. Supplying ``kind`` renders the
    real template instead, which is the only way to verify a template before a
    live run depends on it.
    """

    group_ids: list[int] | None = None
    kind: Literal["plain", "success", "failure"] = "plain"
    pipeline_name: str | None = None


class PreviewIn(BaseModel):
    """Template-preview payload.

    ``template`` previews unsaved editor text; omitted, the saved template for
    ``kind`` (including any per-pipeline override) is used.
    """

    kind: Literal["success", "failure"] = "failure"
    pipeline_name: str | None = None
    template: str | None = None


class NotificationConditionIn(BaseModel):
    """Create/update payload for a condition check."""

    name: str = Field(min_length=1, max_length=200)
    condition_type: Literal["pipeline_idle", "data_freshness"]
    enabled: bool = True
    threshold_minutes: int = Field(ge=5, le=60 * 24 * 30)
    check_frequency_minutes: int = 60
    pipeline_name: str | None = None
    warehouse_connection_id: int | None = None
    schema_name: str | None = None
    table_name: str | None = None
    timestamp_column: str | None = None
    group_ids: list[int] = []
    message_template: str = ""
    notify_on_recovery: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_group(g: NotificationGroup) -> dict[str, Any]:
    return {"id": g.id, "name": g.name, "channels": g.channels or {}}


def _serialize_config(c: PipelineNotificationConfig) -> dict[str, Any]:
    return {
        "pipeline_connection_id": c.pipeline_connection_id,
        "enabled": c.enabled,
        "notify_on_success": c.notify_on_success,
        "notify_on_failure": c.notify_on_failure,
        "success_message": c.success_message,
        "failure_message": c.failure_message,
        "poll_frequency_minutes": c.poll_frequency_minutes,
        "success_group_ids": c.success_group_ids or [],
        "failure_group_ids": c.failure_group_ids or [],
        "pipeline_overrides": c.pipeline_overrides or {},
        "min_interval_minutes": c.min_interval_minutes or 0,
        "quiet_hours_start": c.quiet_hours_start,
        "quiet_hours_end": c.quiet_hours_end,
        "quiet_hours_tz": c.quiet_hours_tz or "UTC",
        "quiet_hours_include_failures": c.quiet_hours_include_failures,
        "last_polled_at": c.last_polled_at.isoformat() if c.last_polled_at else None,
        # The UI shows "next check due" — derived here so it uses server time.
        "next_poll_due_at": (
            (c.last_polled_at + timedelta(minutes=c.poll_frequency_minutes)).isoformat()
            if c.last_polled_at
            else None
        ),
    }


def _serialize_delivery(d: NotificationDelivery) -> dict[str, Any]:
    return {
        "id": d.id,
        "source": d.source,
        "pipeline_name": d.pipeline_name,
        "run_id": d.run_id,
        "condition_id": d.condition_id,
        "subject": d.subject,
        "message": d.message,
        "group_ids": d.group_ids or [],
        "sent_count": d.sent_count,
        "failed_count": d.failed_count,
        "details": d.details or [],
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _validate_timezone(tz_name: str) -> str:
    """Return ``tz_name`` if the platform knows it, else UTC.

    Stored unvalidated, a typo would silently disable quiet hours at evaluation
    time (where the fallback lives) with nothing in the UI to explain why.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: PLC0415

    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return tz_name


async def _conn_or_404(connection_id: int, org_id: int, db: AsyncSession) -> DataPipelineConnection:
    conn = (
        await db.execute(
            select(DataPipelineConnection).where(
                DataPipelineConnection.id == connection_id,
                DataPipelineConnection.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Pipeline connection not found")
    return conn


# ---------------------------------------------------------------------------
# Recipients (for email/SMS pickers)
# ---------------------------------------------------------------------------


@router.get("/notification-recipients")
async def list_recipients(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return org users for the email/SMS destination pickers."""
    rows = await db.execute(
        select(User).where(User.org_id == current_user.org_id, is_true(User.is_active))
        .order_by(User.email)
    )
    return [
        {
            "id": u.id,
            "label": (
                u.display_name
                or f"{u.first_name or ''} {u.last_name or ''}".strip()
                or u.email
            ),
            "email": u.email,
            "phone_number": u.phone_number,
        }
        for u in rows.scalars().all()
    ]


# ---------------------------------------------------------------------------
# Notification groups
# ---------------------------------------------------------------------------


@router.get("/notification-groups")
async def list_groups(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """List the org's notification groups."""
    rows = await db.execute(
        select(NotificationGroup)
        .where(NotificationGroup.org_id == current_user.org_id)
        .order_by(NotificationGroup.name)
    )
    return [_serialize_group(g) for g in rows.scalars().all()]


@router.post("/notification-groups", status_code=201)
async def create_group(
    data: NotificationGroupIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create a notification group."""
    group = NotificationGroup(org_id=current_user.org_id, name=data.name, channels=data.channels)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    logger.info("notification_group.created", org_id=current_user.org_id, group_id=group.id)
    return _serialize_group(group)


@router.put("/notification-groups/{group_id}")
async def update_group(
    group_id: int,
    data: NotificationGroupIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update a notification group."""
    group = (
        await db.execute(
            select(NotificationGroup).where(
                NotificationGroup.id == group_id,
                NotificationGroup.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Notification group not found")
    group.name = data.name
    group.channels = data.channels
    await db.commit()
    return _serialize_group(group)


@router.delete("/notification-groups/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a notification group."""
    group = (
        await db.execute(
            select(NotificationGroup).where(
                NotificationGroup.id == group_id,
                NotificationGroup.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Notification group not found")
    await db.delete(group)
    await db.commit()


# ---------------------------------------------------------------------------
# Per-connection notification config
# ---------------------------------------------------------------------------


@router.get("/data-pipelines/{connection_id}/notifications")
async def get_config(
    connection_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return the connection's notification config (defaults if not yet saved)."""
    await _conn_or_404(connection_id, current_user.org_id, db)
    cfg = (
        await db.execute(
            select(PipelineNotificationConfig).where(
                PipelineNotificationConfig.pipeline_connection_id == connection_id,
                PipelineNotificationConfig.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        return {
            "pipeline_connection_id": connection_id,
            "enabled": False,
            "notify_on_success": False,
            "notify_on_failure": True,
            "success_message": "✅ Pipeline {pipeline} succeeded on {connection}.",
            "failure_message": "❌ Pipeline {pipeline} failed on {connection}: {message}",
            "poll_frequency_minutes": 60,
            "success_group_ids": [],
            "failure_group_ids": [],
            "pipeline_overrides": {},
            "last_polled_at": None,
        }
    return _serialize_config(cfg)


@router.put("/data-pipelines/{connection_id}/notifications")
async def upsert_config(
    connection_id: int,
    data: NotificationConfigIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create or update the connection's notification config."""
    await _conn_or_404(connection_id, current_user.org_id, db)
    freq = max(_MIN_POLL_MINUTES, min(_MAX_POLL_MINUTES, data.poll_frequency_minutes))

    cfg = (
        await db.execute(
            select(PipelineNotificationConfig).where(
                PipelineNotificationConfig.pipeline_connection_id == connection_id,
                PipelineNotificationConfig.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        cfg = PipelineNotificationConfig(
            org_id=current_user.org_id, pipeline_connection_id=connection_id
        )
        db.add(cfg)
    cfg.enabled = data.enabled
    cfg.notify_on_success = data.notify_on_success
    cfg.notify_on_failure = data.notify_on_failure
    cfg.success_message = data.success_message
    cfg.failure_message = data.failure_message
    cfg.poll_frequency_minutes = freq
    cfg.success_group_ids = data.success_group_ids
    cfg.failure_group_ids = data.failure_group_ids
    cfg.pipeline_overrides = data.pipeline_overrides
    cfg.min_interval_minutes = data.min_interval_minutes
    # A half-set window would silently never trigger; treat it as "off" so the
    # saved state matches what the UI shows.
    both_bounds = data.quiet_hours_start is not None and data.quiet_hours_end is not None
    cfg.quiet_hours_start = data.quiet_hours_start if both_bounds else None
    cfg.quiet_hours_end = data.quiet_hours_end if both_bounds else None
    cfg.quiet_hours_tz = _validate_timezone(data.quiet_hours_tz)
    cfg.quiet_hours_include_failures = data.quiet_hours_include_failures
    await db.commit()
    await db.refresh(cfg)
    logger.info(
        "pipeline_notif.config_saved",
        org_id=current_user.org_id,
        connection_id=connection_id,
    )
    return _serialize_config(cfg)


async def _render_for_kind(
    conn: DataPipelineConnection,
    cfg: PipelineNotificationConfig | None,
    kind: str,
    pipeline_name: str | None,
    template_override: str | None,
) -> dict[str, Any]:
    """Render a run-alert template against a real recent run, or a sample.

    Previewing against the newest matching run is what makes a template
    trustworthy — placeholders that are always empty for a given provider show up
    immediately instead of in the first real incident.
    """
    from app.services import pipeline_providers as providers  # noqa: PLC0415
    from app.services.pipeline_poller import (  # noqa: PLC0415
        _decrypt_secret,
        _render,
        _terminal_kind,
        build_context,
        effective_settings,
    )

    run: dict[str, Any] | None = None
    provider = providers.get_provider(conn.provider)
    if provider is not None and provider.meta.implemented:
        try:
            result = await provider.list_runs(
                conn.config or {}, _decrypt_secret(conn), limit=50, days=14
            )
            for candidate in result.get("runs", []):
                if pipeline_name and candidate.get("name") != pipeline_name:
                    continue
                if _terminal_kind(candidate.get("status")) != kind:
                    continue
                run = candidate
                break
        except Exception as exc:  # noqa: BLE001 — preview must work offline
            logger.info("pipeline_notif.preview_fetch_failed", error=str(exc))

    used_sample = run is None
    if run is None:
        now = datetime.now(UTC)
        run = {
            "run_id": "00000000-0000-0000-0000-000000000000",
            "name": pipeline_name or "SamplePipeline",
            "status": "Succeeded" if kind == "success" else "Failed",
            "started_at": (now - timedelta(minutes=7)).isoformat(),
            "ended_at": now.isoformat(),
            "duration_ms": 7 * 60 * 1000,
            "message": ""
            if kind == "success"
            else "ErrorCode=UserErrorFileNotFound: the source file was not found.",
            "invoked_by": "Scheduled trigger",
            "invoked_by_type": "ScheduleTrigger",
            "parent_run_id": "",
        }

    if template_override is not None:
        template = template_override
    elif cfg is not None:
        eff = effective_settings(cfg, run.get("name") or "pipeline")
        template = eff["success_message"] if kind == "success" else eff["failure_message"]
    else:
        template = (
            "✅ Pipeline {pipeline} succeeded on {connection}."
            if kind == "success"
            else "❌ Pipeline {pipeline} failed on {connection}: {message}"
        )

    ctx = build_context(run, conn)
    return {
        "subject": f"Pipeline {run.get('name') or 'pipeline'} {kind} — {conn.name}",
        "message": _render(template, ctx),
        "template": template,
        "used_sample": used_sample,
        "run_id": run.get("run_id"),
        "context": {k: str(v) for k, v in ctx.items()},
    }


@router.post("/data-pipelines/{connection_id}/notifications/preview")
async def preview_notification(
    connection_id: int,
    data: PreviewIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Render a message template without sending anything."""
    conn = await _conn_or_404(connection_id, current_user.org_id, db)
    cfg = (
        await db.execute(
            select(PipelineNotificationConfig).where(
                PipelineNotificationConfig.pipeline_connection_id == connection_id,
                PipelineNotificationConfig.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    return await _render_for_kind(conn, cfg, data.kind, data.pipeline_name, data.template)


@router.post("/data-pipelines/{connection_id}/notifications/test")
async def test_notification(
    connection_id: int,
    data: TestNotificationIn | None = None,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Send a test notification to chosen (or all configured) groups.

    With ``kind`` set to success/failure the real template is rendered, so the
    test verifies the message operators will actually receive.
    """
    from app.services.pipeline_notifications import send_to_groups  # noqa: PLC0415

    payload = data or TestNotificationIn()
    conn = await _conn_or_404(connection_id, current_user.org_id, db)
    cfg = (
        await db.execute(
            select(PipelineNotificationConfig).where(
                PipelineNotificationConfig.pipeline_connection_id == connection_id,
                PipelineNotificationConfig.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()

    if payload.group_ids:
        # Only groups belonging to this org may be targeted.
        valid = set(
            (
                await db.execute(
                    select(NotificationGroup.id).where(
                        NotificationGroup.org_id == current_user.org_id,
                        NotificationGroup.id.in_(payload.group_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        group_ids = [g for g in payload.group_ids if g in valid]
        if not group_ids:
            raise HTTPException(status_code=404, detail="Notification group not found")
    else:
        group_ids = (
            list({*(cfg.success_group_ids or []), *(cfg.failure_group_ids or [])}) if cfg else []
        )
    if not group_ids:
        raise HTTPException(status_code=400, detail="No notification groups configured.")

    if payload.kind == "plain":
        subject = f"Test notification — {conn.name}"
        message = f"✅ This is a test notification from the '{conn.name}' pipeline connection."
    else:
        rendered = await _render_for_kind(conn, cfg, payload.kind, payload.pipeline_name, None)
        subject = f"[TEST] {rendered['subject']}"
        message = f"{rendered['message']}\n\n(This is a test — no pipeline actually ran.)"

    result = await send_to_groups(
        db,
        current_user.org_id,
        group_ids,
        subject=subject,
        message=message,
        source="test",
        pipeline_connection_id=connection_id,
        pipeline_name=payload.pipeline_name,
    )
    # send_to_groups only flushes its audit row; the request owns the commit.
    await db.commit()
    return result


@router.get("/data-pipelines/{connection_id}/notification-deliveries")
async def list_deliveries(
    connection_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    source: str | None = None,
    status: Literal["all", "sent", "failed"] = "all",
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return recent notification delivery attempts for this connection.

    Admin-only: rows carry the message body and (redacted) destinations.
    """
    await _conn_or_404(connection_id, current_user.org_id, db)
    query = select(NotificationDelivery).where(
        NotificationDelivery.org_id == current_user.org_id,
        NotificationDelivery.pipeline_connection_id == connection_id,
    )
    if source:
        query = query.where(NotificationDelivery.source == source)
    if status == "failed":
        query = query.where(NotificationDelivery.failed_count > 0)
    elif status == "sent":
        query = query.where(NotificationDelivery.failed_count == 0)
    rows = (
        (await db.execute(query.order_by(NotificationDelivery.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return {"deliveries": [_serialize_delivery(d) for d in rows]}


@router.get("/data-pipelines/{connection_id}/notification-summary")
async def notification_summary(
    connection_id: int,
    days: int = Query(default=7, ge=1, le=90),
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Aggregate delivery counts for the health header on the notifications tab."""
    await _conn_or_404(connection_id, current_user.org_id, db)
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                NotificationDelivery.source,
                func.count(NotificationDelivery.id),
                func.coalesce(func.sum(NotificationDelivery.sent_count), 0),
                func.coalesce(func.sum(NotificationDelivery.failed_count), 0),
            )
            .where(
                NotificationDelivery.org_id == current_user.org_id,
                NotificationDelivery.pipeline_connection_id == connection_id,
                NotificationDelivery.created_at >= since,
            )
            .group_by(NotificationDelivery.source)
        )
    ).all()
    by_source = {
        str(src): {"attempts": int(n), "sent": int(sent), "failed": int(failed)}
        for src, n, sent, failed in rows
    }
    last = (
        await db.execute(
            select(NotificationDelivery.created_at)
            .where(
                NotificationDelivery.org_id == current_user.org_id,
                NotificationDelivery.pipeline_connection_id == connection_id,
            )
            .order_by(NotificationDelivery.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "days": days,
        "by_source": by_source,
        "attempts": sum(v["attempts"] for v in by_source.values()),
        "sent": sum(v["sent"] for v in by_source.values()),
        "failed": sum(v["failed"] for v in by_source.values()),
        "last_delivery_at": last.isoformat() if last else None,
    }


@router.get("/data-pipelines/{connection_id}/notification-status")
async def get_notification_status(
    connection_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return non-sensitive notification status so the Pipelines tab can badge each pipeline.

    Available to anyone who can view the connection. Returns the effective
    default success/failure flags and per-pipeline boolean overrides (no groups,
    webhooks, or message text). The client combines this with the pipeline list.
    """
    from app.routers.data_pipelines import _require_view  # noqa: PLC0415

    await _require_view(connection_id, current_user, db)
    cfg = (
        await db.execute(
            select(PipelineNotificationConfig).where(
                PipelineNotificationConfig.pipeline_connection_id == connection_id,
                PipelineNotificationConfig.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        return {
            "enabled": False,
            "notify_on_success": False,
            "notify_on_failure": False,
            "overrides": {},
        }

    from app.services.pipeline_poller import normalize_override  # noqa: PLC0415

    overrides: dict[str, dict[str, bool]] = {}
    for name, raw in (cfg.pipeline_overrides or {}).items():
        ov = normalize_override(raw)
        entry: dict[str, bool] = {}
        if "notify_on_success" in ov:
            entry["notify_on_success"] = bool(ov["notify_on_success"])
        if "notify_on_failure" in ov:
            entry["notify_on_failure"] = bool(ov["notify_on_failure"])
        if entry:
            overrides[name] = entry
    return {
        "enabled": cfg.enabled,
        "notify_on_success": cfg.notify_on_success,
        "notify_on_failure": cfg.notify_on_failure,
        "overrides": overrides,
    }


# ---------------------------------------------------------------------------
# Condition checks (pipeline idle / data freshness)
# ---------------------------------------------------------------------------


def _serialize_condition(c: NotificationCondition) -> dict[str, Any]:
    return {
        "id": c.id,
        "pipeline_connection_id": c.pipeline_connection_id,
        "name": c.name,
        "condition_type": c.condition_type,
        "enabled": c.enabled,
        "threshold_minutes": c.threshold_minutes,
        "check_frequency_minutes": c.check_frequency_minutes,
        "pipeline_name": c.pipeline_name,
        "warehouse_connection_id": c.warehouse_connection_id,
        "schema_name": c.schema_name,
        "table_name": c.table_name,
        "timestamp_column": c.timestamp_column,
        "group_ids": c.group_ids or [],
        "message_template": c.message_template or "",
        "notify_on_recovery": c.notify_on_recovery,
        "is_triggered": c.is_triggered,
        "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None,
        "last_observed_at": c.last_observed_at.isoformat() if c.last_observed_at else None,
        "last_error": c.last_error,
    }


async def _validate_condition(
    data: NotificationConditionIn, org_id: int, db: AsyncSession
) -> None:
    """Reject condition payloads with missing/invalid type-specific fields."""
    if data.condition_type == "data_freshness":
        if not data.table_name or not is_valid_identifier(data.table_name):
            raise HTTPException(
                status_code=400,
                detail="table_name (a plain SQL identifier) is required for data_freshness",
            )
        if not data.timestamp_column or not is_valid_identifier(data.timestamp_column):
            raise HTTPException(
                status_code=400,
                detail="timestamp_column (a plain SQL identifier) is required for data_freshness",
            )
        if data.schema_name and not is_valid_identifier(data.schema_name):
            raise HTTPException(
                status_code=400, detail="schema_name must be a plain SQL identifier"
            )
        if data.warehouse_connection_id is not None:
            wh = await db.execute(
                select(WarehouseConnection.id).where(
                    WarehouseConnection.id == data.warehouse_connection_id,
                    WarehouseConnection.org_id == org_id,
                )
            )
            if wh.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Warehouse connection not found")


def _apply_condition_payload(cond: NotificationCondition, data: NotificationConditionIn) -> None:
    cond.name = data.name
    cond.condition_type = data.condition_type
    cond.enabled = data.enabled
    cond.threshold_minutes = data.threshold_minutes
    cond.check_frequency_minutes = max(
        _MIN_POLL_MINUTES, min(_MAX_POLL_MINUTES, data.check_frequency_minutes)
    )
    cond.pipeline_name = data.pipeline_name if data.condition_type == "pipeline_idle" else None
    is_freshness = data.condition_type == "data_freshness"
    cond.warehouse_connection_id = data.warehouse_connection_id if is_freshness else None
    cond.schema_name = data.schema_name if is_freshness else None
    cond.table_name = data.table_name if is_freshness else None
    cond.timestamp_column = data.timestamp_column if is_freshness else None
    cond.group_ids = data.group_ids
    cond.message_template = data.message_template
    cond.notify_on_recovery = data.notify_on_recovery


async def _condition_or_404(
    condition_id: int, org_id: int, db: AsyncSession
) -> NotificationCondition:
    cond = (
        await db.execute(
            select(NotificationCondition).where(
                NotificationCondition.id == condition_id,
                NotificationCondition.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cond is None:
        raise HTTPException(status_code=404, detail="Condition not found")
    return cond


@router.get("/data-pipelines/{connection_id}/conditions")
async def list_conditions(
    connection_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """List condition checks for a pipeline connection."""
    await _conn_or_404(connection_id, current_user.org_id, db)
    conditions = (
        (
            await db.execute(
                select(NotificationCondition)
                .where(
                    NotificationCondition.pipeline_connection_id == connection_id,
                    NotificationCondition.org_id == current_user.org_id,
                )
                .order_by(NotificationCondition.id)
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_condition(c) for c in conditions]


@router.post("/data-pipelines/{connection_id}/conditions", status_code=201)
async def create_condition(
    connection_id: int,
    data: NotificationConditionIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create a condition check on a pipeline connection."""
    await _conn_or_404(connection_id, current_user.org_id, db)
    await _validate_condition(data, current_user.org_id, db)
    cond = NotificationCondition(
        org_id=current_user.org_id, pipeline_connection_id=connection_id
    )
    _apply_condition_payload(cond, data)
    db.add(cond)
    await db.commit()
    await db.refresh(cond)
    logger.info("pipeline_notif.condition_created", condition_id=cond.id, type=cond.condition_type)
    return _serialize_condition(cond)


@router.put("/notification-conditions/{condition_id}")
async def update_condition(
    condition_id: int,
    data: NotificationConditionIn,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update a condition check."""
    cond = await _condition_or_404(condition_id, current_user.org_id, db)
    await _validate_condition(data, current_user.org_id, db)
    _apply_condition_payload(cond, data)
    await db.commit()
    await db.refresh(cond)
    return _serialize_condition(cond)


@router.delete("/notification-conditions/{condition_id}", status_code=204)
async def delete_condition(
    condition_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a condition check."""
    cond = await _condition_or_404(condition_id, current_user.org_id, db)
    await db.delete(cond)
    await db.commit()


@router.post("/notification-conditions/{condition_id}/check")
async def run_condition_check(
    condition_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Evaluate a condition immediately and return the result.

    A dry run: probes the source and reports triggered/age without changing
    the condition's alert state or sending notifications.
    """
    from app.services.condition_checker import evaluate_condition  # noqa: PLC0415

    cond = await _condition_or_404(condition_id, current_user.org_id, db)
    result = await evaluate_condition(db, cond)
    observed = result.get("observed_at")
    return {
        "ok": result["ok"],
        "triggered": result["triggered"],
        "observed_at": observed.isoformat() if observed else None,
        "age_minutes": result["age_minutes"],
        "error": result["error"],
    }
