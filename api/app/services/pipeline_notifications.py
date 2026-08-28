"""Delivery of pipeline-monitoring notifications to notification groups.

Webhook channels (Slack, Teams, Google Chat) post directly over HTTP. Email uses
the configured SMTP server; SMS uses the configured Twilio account. Email/SMS
resolve to each referenced user's email / phone_number. Every send is
best-effort and isolated — one bad destination never blocks the others.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_notification import NotificationGroup
from app.models.user import User

logger = structlog.get_logger(__name__)


async def _post_webhook(url: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code < 400:
            return True, None
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except httpx.HTTPError as exc:
        return False, str(exc)


async def _send_slack(url: str, message: str) -> tuple[bool, str | None]:
    return await _post_webhook(url, {"text": message})


async def _send_gchat(url: str, message: str) -> tuple[bool, str | None]:
    return await _post_webhook(url, {"text": message})


async def _send_teams(url: str, subject: str, message: str) -> tuple[bool, str | None]:
    # Teams incoming webhooks accept the legacy MessageCard schema.
    return await _post_webhook(
        url,
        {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": subject or "Pipeline notification",
            "text": message,
        },
    )


def _send_email_sync(
    recipients: list[str], subject: str, body: str, html_body: str | None = None
) -> None:
    """Send one email to all recipients via SMTP (blocking; run in a thread)."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from_address or settings.smtp_user or "noreply@biplatform"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    # The plain part is set first so it stays the fallback: a client that cannot
    # render HTML still gets the link as text it can copy.
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def _send_email(
    recipients: list[str], subject: str, body: str, html_body: str | None = None
) -> tuple[bool, str | None]:
    if not settings.smtp_host:
        logger.warning("pipeline_notif.email_skipped", reason="SMTP not configured")
        return False, "SMTP is not configured (set SMTP_HOST)."
    try:
        await asyncio.to_thread(_send_email_sync, recipients, subject, body, html_body)
        return True, None
    except Exception as exc:  # noqa: BLE001 — surface any SMTP error as a result
        return False, str(exc)


async def _send_sms(phone: str, message: str) -> tuple[bool, str | None]:
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_from_number
    if not (sid and token and from_number):
        logger.warning("pipeline_notif.sms_skipped", reason="Twilio not configured")
        return False, "Twilio is not configured (set TWILIO_* env vars)."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data={"From": from_number, "To": phone, "Body": message[:1500]},
                auth=(sid, token),
            )
        if resp.status_code < 400:
            return True, None
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except httpx.HTTPError as exc:
        return False, str(exc)


async def _resolve_users(
    db: AsyncSession, org_id: int, user_ids: list[int]
) -> dict[int, User]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User).where(User.org_id == org_id, User.id.in_(user_ids))
    )
    return {u.id: u for u in rows.scalars().all()}


def _redact(target: str, channel: str) -> str:
    """Shorten a webhook URL for storage so the history never holds a live secret.

    Incoming webhook URLs *are* the credential, so the recorded target keeps only
    enough to identify which destination it was.
    """
    if channel in ("slack", "teams", "gchat") and "://" in target:
        host = target.split("://", 1)[1].split("/", 1)[0]
        return f"{host}/…{target[-6:]}" if len(target) > 6 else host
    if channel == "sms" and len(target) > 4:
        return f"…{target[-4:]}"
    return target


async def send_to_groups(
    db: AsyncSession,
    org_id: int,
    group_ids: list[int],
    subject: str,
    message: str,
    *,
    source: str = "test",
    pipeline_connection_id: int | None = None,
    condition_id: int | None = None,
    pipeline_name: str | None = None,
    run_id: str | None = None,
    record: bool = True,
) -> dict[str, Any]:
    """Send ``message`` to every destination in the given notification groups.

    When ``record`` is set, the attempt is written to ``notification_deliveries``
    with the per-destination outcome. The row is added to the session but not
    committed — the caller owns the transaction. A logging failure never
    propagates: losing the audit row must not lose the notification.

    Returns {"sent": n, "failed": n, "details": [{channel, target, ok, error}]}.
    """
    if not group_ids:
        return {"sent": 0, "failed": 0, "details": []}

    groups = (
        await db.execute(
            select(NotificationGroup).where(
                NotificationGroup.org_id == org_id,
                NotificationGroup.id.in_(group_ids),
            )
        )
    ).scalars().all()

    slack: set[str] = set()
    teams: set[str] = set()
    gchat: set[str] = set()
    email_ids: set[int] = set()
    sms_ids: set[int] = set()
    for g in groups:
        ch = g.channels or {}
        slack.update(ch.get("slack", []) or [])
        teams.update(ch.get("teams", []) or [])
        gchat.update(ch.get("gchat", []) or [])
        email_ids.update(int(x) for x in (ch.get("email", []) or []))
        sms_ids.update(int(x) for x in (ch.get("sms", []) or []))

    users = await _resolve_users(db, org_id, list(email_ids | sms_ids))
    emails = [users[i].email for i in email_ids if i in users and users[i].email]
    phones = [users[i].phone_number for i in sms_ids if i in users and users[i].phone_number]

    details: list[dict[str, Any]] = []

    async def _record(channel: str, target: str, result: tuple[bool, str | None]) -> None:
        ok, err = result
        details.append({"channel": channel, "target": target, "ok": ok, "error": err})

    for url in slack:
        await _record("slack", url, await _send_slack(url, message))
    for url in teams:
        await _record("teams", url, await _send_teams(url, subject, message))
    for url in gchat:
        await _record("gchat", url, await _send_gchat(url, message))
    if emails:
        await _record("email", ", ".join(emails), await _send_email(emails, subject, message))
    for phone in phones:
        await _record("sms", phone, await _send_sms(phone, message))

    sent = sum(1 for d in details if d["ok"])
    result = {"sent": sent, "failed": len(details) - sent, "details": details}

    if record:
        await _record_delivery(
            db,
            org_id=org_id,
            group_ids=group_ids,
            subject=subject,
            message=message,
            details=details,
            sent=sent,
            source=source,
            pipeline_connection_id=pipeline_connection_id,
            condition_id=condition_id,
            pipeline_name=pipeline_name,
            run_id=run_id,
        )
    return result


async def _record_delivery(
    db: AsyncSession,
    *,
    org_id: int,
    group_ids: list[int],
    subject: str,
    message: str,
    details: list[dict[str, Any]],
    sent: int,
    source: str,
    pipeline_connection_id: int | None,
    condition_id: int | None,
    pipeline_name: str | None,
    run_id: str | None,
) -> None:
    """Append a delivery-history row. Swallows its own errors by design."""
    from app.models.pipeline_notification import NotificationDelivery  # noqa: PLC0415

    try:
        db.add(
            NotificationDelivery(
                org_id=org_id,
                pipeline_connection_id=pipeline_connection_id,
                condition_id=condition_id,
                source=source,
                pipeline_name=pipeline_name,
                run_id=run_id,
                subject=subject[:2000],
                message=message[:4000],
                group_ids=list(group_ids),
                sent_count=sent,
                failed_count=len(details) - sent,
                details=[
                    {
                        "channel": d["channel"],
                        "target": _redact(str(d["target"]), str(d["channel"])),
                        "ok": d["ok"],
                        "error": (str(d["error"])[:500] if d["error"] else None),
                    }
                    for d in details
                ],
            )
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001 — never lose a notification over its audit row
        logger.warning("pipeline_notif.delivery_log_failed", error=str(exc))
