"""Notification event dispatcher.

Routes notification events to each subscribed user's enabled channels using
the delivery adapters in app.services.pipeline_notifications (SMTP email,
Twilio SMS, Slack/Teams/Google Chat webhooks). Channels are filtered by
NOTIFICATION_CHANNELS_ENABLED, rate-limited per user per event type, and
every delivery is appended to a Redis stream as an audit trail.

Webhook channels (slack/teams/gchat) are per-user: the preference's ``config``
JSON must carry a ``webhook_url``; preferences without one are skipped.
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy import select

from app.config import settings
from app.redis import get_redis
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

_RATE_LIMIT_SECONDS = 300  # 1 notification per user per event type per 5 min


def _build_subject_and_message(event_type: str, payload: dict) -> tuple[str, str]:
    """Derive a subject and body from the event payload.

    Payloads may carry explicit 'subject'/'message' keys; anything else is
    rendered as a readable key: value list.
    """
    subject = payload.get("subject") or f"BI Platform: {event_type.replace('_', ' ')}"
    message = payload.get("message")
    if not message:
        details = {k: v for k, v in payload.items() if k not in ("subject", "message")}
        lines = [f"{k}: {v}" for k, v in details.items()]
        message = "\n".join(lines) or subject
    return subject, message


async def dispatch_event(
    event_type: str,
    payload: dict,
    org_id: int | None,
) -> None:
    """Dispatch a notification event to all subscribed users.

    Reads enabled NotificationPreference rows for the org and event type,
    filters channels to NOTIFICATION_CHANNELS_ENABLED, rate-limits per user
    per event type, delivers via the channel adapter, and records each
    delivery on the notifications:{channel} Redis stream.

    Args:
        event_type: The event type (e.g. 'pipeline_failure', 'data_freshness').
        payload: Event metadata; 'subject' and 'message' keys are used when
            present, other keys are rendered into the message body.
        org_id: Organisation scope for user lookup. None is a no-op (callers
            outside a request context may not know the org).
    """
    if org_id is None:
        logger.warning("notification.skipped_no_org", event_type=event_type)
        return

    from app.database import get_app_db  # noqa: PLC0415 — avoid import cycle
    from app.models.notification import NotificationPreference  # noqa: PLC0415

    enabled_channels = set(settings.notification_channels_list)
    subject, message = _build_subject_and_message(event_type, payload)

    async for db in get_app_db():
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.org_id == org_id,
                NotificationPreference.event_type == event_type,
                is_true(NotificationPreference.enabled),
            )
        )
        subscribed = result.scalars().all()

        try:
            redis_client = await get_redis()
        except Exception:  # noqa: BLE001 — no Redis → deliver without rate limiting
            redis_client = None

        for pref in subscribed:
            if pref.channel not in enabled_channels:
                continue

            if redis_client is not None:
                rate_key = f"rate_limit:{org_id}:{pref.user_id}:{event_type}"
                try:
                    was_set = await redis_client.set(rate_key, "1", ex=_RATE_LIMIT_SECONDS, nx=True)
                    if not was_set:
                        continue
                except Exception:  # noqa: BLE001
                    pass

            ok, error = await _deliver(db, pref, subject, message)
            if redis_client is not None:
                try:
                    await redis_client.xadd(
                        f"notifications:{pref.channel}",
                        {
                            "event_type": event_type,
                            "user_id": str(pref.user_id),
                            "payload": json.dumps(payload, default=str),
                            "ok": "1" if ok else "0",
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
            if ok:
                logger.info("notification.dispatched", channel=pref.channel, user_id=pref.user_id)
            else:
                logger.warning(
                    "notification.delivery_failed",
                    channel=pref.channel,
                    user_id=pref.user_id,
                    error=error,
                )
        break


async def _deliver(db, pref, subject: str, message: str) -> tuple[bool, str | None]:  # noqa: ANN001
    """Deliver one notification through the preference's channel adapter."""
    from app.models.user import User  # noqa: PLC0415
    from app.services import pipeline_notifications as delivery  # noqa: PLC0415

    channel = pref.channel
    config = pref.config or {}

    if channel in ("slack", "teams", "gchat"):
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return False, "No webhook_url configured on this preference"
        if channel == "slack":
            return await delivery._send_slack(webhook_url, message)
        if channel == "gchat":
            return await delivery._send_gchat(webhook_url, message)
        return await delivery._send_teams(webhook_url, subject, message)

    user = (await db.execute(select(User).where(User.id == pref.user_id))).scalar_one_or_none()
    if user is None:
        return False, "User not found"

    if channel == "email":
        if not user.email:
            return False, "User has no email address"
        return await delivery._send_email([user.email], subject, message)

    if channel == "sms":
        phone = getattr(user, "phone_number", None)
        if not phone:
            return False, "User has no phone number"
        return await delivery._send_sms(phone, message)

    return False, f"Unknown channel '{channel}'"
