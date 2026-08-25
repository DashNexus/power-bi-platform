"""Background poller that monitors pipeline connections and fires notifications.

Runs as a single in-process asyncio loop (guarded by a Redis lock so only one
worker polls per tick). Each enabled PipelineNotificationConfig is polled at its
configured cadence: recent runs are fetched via the connection's provider, new
terminal runs (succeeded/failed) are matched against the config's
success/failure toggles and per-pipeline overrides, and matching runs are sent
to the configured notification groups. Runs already handled are tracked in
``notified_run_ids`` so nothing is sent twice; the first poll only seeds that
set (no backfill blast).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_pipeline import DataPipelineConnection
from app.models.pipeline_notification import PipelineNotificationConfig
from app.services import pipeline_providers as providers
from app.services.alert_suppression import should_suppress, throttle_key
from app.services.pipeline_notifications import send_to_groups
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

_POLL_TICK_SECONDS = 60
_LOOKBACK_DAYS = 2
_MAX_TRACKED_RUN_IDS = 1000
# Throttle entries are only useful for as long as the longest throttle window;
# a week is far beyond any sane min_interval_minutes.
_THROTTLE_RETENTION = timedelta(days=7)
# Delivery history retention. Trimmed once per tick rather than per config.
_DELIVERY_RETENTION_DAYS = 30
_SUCCESS = {"succeeded", "completed", "success"}
_FAILURE = {"failed", "crashed", "error", "timedout"}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # noqa: D105
        return ""


def _render(template: str, ctx: dict[str, Any]) -> str:
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:  # noqa: BLE001 — never let a bad template break the poller
        return template


def _terminal_kind(status: str | None) -> str | None:
    """Return 'success' | 'failure' | None (non-terminal) for a run status."""
    s = (status or "").lower()
    if any(k in s for k in _SUCCESS):
        return "success"
    if any(k in s for k in _FAILURE):
        return "failure"
    return None


def normalize_override(val: object) -> dict[str, Any]:
    """Coerce a pipeline_overrides value to the current object shape.

    Handles the legacy boolean shape ({name: false} meant "all off").
    """
    if isinstance(val, dict):
        return val
    if val is False:
        return {"notify_on_success": False, "notify_on_failure": False}
    return {}


def effective_settings(cfg: PipelineNotificationConfig, pipeline_name: str) -> dict[str, Any]:
    """Return the effective notify flags + message templates for one pipeline.

    Per-pipeline overrides win; unset fields inherit the connection defaults.
    """
    ov = normalize_override((cfg.pipeline_overrides or {}).get(pipeline_name))
    return {
        "notify_on_success": ov.get("notify_on_success", cfg.notify_on_success),
        "notify_on_failure": ov.get("notify_on_failure", cfg.notify_on_failure),
        "success_message": ov.get("success_message") or cfg.success_message,
        "failure_message": ov.get("failure_message") or cfg.failure_message,
    }


def _human_duration(ms: object) -> str:
    if not isinstance(ms, int | float) or ms <= 0:
        return ""
    s = int(ms // 1000)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def build_context(run: dict[str, Any], conn: DataPipelineConnection) -> dict[str, Any]:
    """Build the message-template context: every run field plus connection info.

    Any run key (run_id, name, status, started_at, ended_at, duration_ms,
    message, invoked_by, invoked_by_type, parent_run_id, …) is usable as a
    placeholder, alongside {pipeline}, {connection}, {provider}, {duration}.
    """
    ctx: dict[str, Any] = {k: ("" if v is None else v) for k, v in run.items()}
    ctx.update(
        {
            "pipeline": run.get("name") or "pipeline",
            "connection": conn.name,
            "provider": conn.provider,
            "duration": _human_duration(run.get("duration_ms")),
        }
    )
    return ctx


def _prune_last_alert_at(entries: dict[str, str], now: datetime) -> dict[str, str]:
    """Drop throttle timestamps older than the retention window."""
    cutoff = now - _THROTTLE_RETENTION
    kept: dict[str, str] = {}
    for key, raw in entries.items():
        try:
            parsed = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed >= cutoff:
            kept[key] = raw
    return kept


def _decrypt_secret(conn: DataPipelineConnection) -> str | None:
    from app.services.crypto import decrypt  # noqa: PLC0415

    if not conn.secret_encrypted:
        return None
    try:
        return decrypt(conn.secret_encrypted)
    except Exception:  # noqa: BLE001
        return None


async def _process_config(db: AsyncSession, cfg: PipelineNotificationConfig) -> None:
    """Poll one connection and dispatch notifications for new terminal runs."""
    conn = (
        await db.execute(
            select(DataPipelineConnection).where(
                DataPipelineConnection.id == cfg.pipeline_connection_id,
                is_true(DataPipelineConnection.is_active),
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        return
    provider = providers.get_provider(conn.provider)
    if provider is None or not provider.meta.implemented:
        return

    try:
        result = await provider.list_runs(
            conn.config or {}, _decrypt_secret(conn), limit=100, days=_LOOKBACK_DAYS
        )
    except providers.PipelineProviderError as exc:
        logger.warning("pipeline_poller.fetch_failed", connection_id=conn.id, error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline_poller.fetch_error", connection_id=conn.id, error=str(exc))
        return

    runs = result.get("runs", [])
    seen: set[str] = set(cfg.notified_run_ids or [])
    first_poll = cfg.last_polled_at is None
    now = datetime.now(UTC)
    # (group_ids, subject, message, kind, pipeline_name, run_id)
    to_send: list[tuple[list[int], str, str, str, str, str]] = []
    events: list[tuple[str, str, str]] = []  # (event_type, subject, message)
    new_ids: list[str] = []
    suppressed: dict[str, int] = {}
    # Local copy so a suppression decision sees alerts queued earlier in this
    # same tick — otherwise a batch of flapping runs would all pass the throttle.
    last_alert_at: dict[str, str] = dict(cfg.last_alert_at or {})

    for run in runs:
        run_id = run.get("run_id")
        if not run_id or run_id in seen:
            continue
        kind = _terminal_kind(run.get("status"))
        if kind is None:
            continue  # still running — revisit next tick
        new_ids.append(run_id)
        if first_poll:
            continue  # seed only: don't notify for pre-existing runs
        pipeline_name = run.get("name") or "pipeline"
        eff = effective_settings(cfg, pipeline_name)
        if kind == "success" and not eff["notify_on_success"]:
            continue
        if kind == "failure" and not eff["notify_on_failure"]:
            continue
        reason = should_suppress(
            kind=kind,
            pipeline_name=pipeline_name,
            now=now,
            min_interval_minutes=cfg.min_interval_minutes or 0,
            last_alert_at=last_alert_at,
            quiet_hours_start=cfg.quiet_hours_start,
            quiet_hours_end=cfg.quiet_hours_end,
            quiet_hours_tz=cfg.quiet_hours_tz,
            quiet_hours_include_failures=cfg.quiet_hours_include_failures,
        )
        if reason is not None:
            suppressed[reason] = suppressed.get(reason, 0) + 1
            continue
        ctx = build_context(run, conn)
        template = eff["success_message"] if kind == "success" else eff["failure_message"]
        groups = cfg.success_group_ids if kind == "success" else cfg.failure_group_ids
        subject = f"Pipeline {pipeline_name} {kind} — {conn.name}"
        message = _render(template, ctx)
        to_send.append((groups or [], subject, message, kind, pipeline_name, run_id))
        last_alert_at[throttle_key(pipeline_name, kind)] = now.isoformat()
        event_type = "pipeline_success" if kind == "success" else "pipeline_failure"
        events.append((event_type, subject, message))

    for groups, subject, message, kind, pipeline_name, run_id in to_send:
        try:
            await send_to_groups(
                db,
                cfg.org_id,
                groups,
                subject,
                message,
                source=f"run_{kind}",
                pipeline_connection_id=conn.id,
                pipeline_name=pipeline_name,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_poller.send_failed", connection_id=conn.id, error=str(exc))

    # Also feed the per-user preference system (pipeline_success/pipeline_failure
    # subscriptions); the dispatcher rate-limits per user per event type.
    from app.services.notifications.dispatcher import dispatch_event  # noqa: PLC0415

    for event_type, subject, message in events:
        try:
            await dispatch_event(
                event_type=event_type,
                payload={"subject": subject, "message": message, "connection": conn.name},
                org_id=cfg.org_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_poller.dispatch_failed", connection_id=conn.id, error=str(exc))

    # Track handled runs (cap size) and record the poll time.
    cfg.notified_run_ids = ([*seen, *new_ids])[-_MAX_TRACKED_RUN_IDS:]
    cfg.last_polled_at = now
    # Prune throttle bookkeeping so the JSON column cannot grow unbounded as
    # pipelines are renamed or removed.
    cfg.last_alert_at = _prune_last_alert_at(last_alert_at, now)
    await db.commit()
    if to_send:
        logger.info("pipeline_poller.notified", connection_id=conn.id, count=len(to_send))
    if suppressed:
        logger.info("pipeline_poller.suppressed", connection_id=conn.id, **suppressed)


async def poll_tick() -> None:
    """Run one poll pass over every enabled config whose cadence is due.

    Also evaluates due notification conditions (pipeline idle / data
    freshness) — see app.services.condition_checker.
    """
    from app.database import AsyncSessionLocal  # noqa: PLC0415
    from app.services.condition_checker import check_due_conditions  # noqa: PLC0415

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        cfgs = (
            await db.execute(
                select(PipelineNotificationConfig).where(
                    is_true(PipelineNotificationConfig.enabled)
                )
            )
        ).scalars().all()
        for cfg in cfgs:
            due = (
                cfg.last_polled_at is None
                or now - cfg.last_polled_at >= timedelta(minutes=cfg.poll_frequency_minutes)
            )
            if due:
                await _process_config(db, cfg)
        await check_due_conditions(db)
        await _prune_delivery_history(db, now)


async def _prune_delivery_history(db: AsyncSession, now: datetime) -> None:
    """Delete delivery rows past the retention window.

    Runs once per tick (not per config) and swallows errors — history hygiene
    must never take the poller down.
    """
    from sqlalchemy import delete  # noqa: PLC0415

    from app.models.pipeline_notification import NotificationDelivery  # noqa: PLC0415

    try:
        cutoff = now - timedelta(days=_DELIVERY_RETENTION_DAYS)
        await db.execute(
            delete(NotificationDelivery).where(NotificationDelivery.created_at < cutoff)
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline_poller.prune_failed", error=str(exc))


async def run_poller_loop() -> None:
    """Forever loop: acquire a short Redis lock and run a poll tick each minute.

    The lock ensures that with multiple API workers only one runs a given tick.
    All errors are swallowed so the loop never dies.
    """
    from app.redis import get_redis  # noqa: PLC0415

    logger.info("pipeline_poller.started")
    while True:
        try:
            lock_ok = True
            try:
                redis_client = await get_redis()
                lock_ok = bool(
                    await redis_client.set(
                        "pipeline_poller:lock", "1", ex=_POLL_TICK_SECONDS - 5, nx=True
                    )
                )
            except Exception:  # noqa: BLE001 — no Redis → still poll (single-node dev)
                lock_ok = True
            if lock_ok:
                await poll_tick()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_poller.tick_error", error=str(exc))
        await asyncio.sleep(_POLL_TICK_SECONDS)
