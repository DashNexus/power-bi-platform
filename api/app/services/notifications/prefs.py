"""Notification preference service.

Manages per-user, per-channel, per-event-type notification preferences
stored in the app DB. Supports bulk updates for toggling all channels
for a given event type at once. Delivery itself lives in the dispatcher
(app.services.notifications.dispatcher), which reuses the adapters in
app.services.pipeline_notifications.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationPreference
from app.schemas.common import PaginatedResponse
from app.schemas.notification import NotificationPrefResponse

logger = structlog.get_logger(__name__)


async def get_user_prefs(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return paginated notification preferences for a user.

    Args:
        db: Async session bound to the application database.
        user_id: The user's primary key.
        org_id: Organisation scope.
        page: 1-indexed page number.
        page_size: Number of preferences per page.

    Returns:
        PaginatedResponse of NotificationPrefResponse.
    """
    offset = (page - 1) * page_size

    count_result = await db.execute(
        select(func.count()).select_from(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.org_id == org_id,
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        # ORDER BY is required: SQL Server rejects OFFSET without one.
        select(NotificationPreference)
        .where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.org_id == org_id,
        )
        .order_by(NotificationPreference.id)
        .offset(offset)
        .limit(page_size)
    )
    prefs = result.scalars().all()
    items = [
        NotificationPrefResponse(
            id=p.id,
            channel=p.channel,
            event_type=p.event_type,
            enabled=p.enabled,
            config=p.config,
        )
        for p in prefs
    ]

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


async def update_pref(
    db: AsyncSession,
    pref_id: int,
    user_id: int,
    data: dict,
) -> bool:
    """Update a single notification preference.

    Args:
        db: Async session bound to the application database.
        pref_id: The preference's primary key.
        user_id: Owner user ID (scope guard).
        data: Fields to update (channel, event_type, enabled, config).

    Returns:
        True if the update succeeded.

    Raises:
        ValueError: If the preference does not belong to this user.
    """
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.id == pref_id,
            NotificationPreference.user_id == user_id,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        raise ValueError(f"Preference {pref_id} not found for user {user_id}")

    for key in ("channel", "event_type", "enabled", "config"):
        if key in data:
            setattr(pref, key, data[key])

    await db.commit()
    logger.info("notification.pref_updated", pref_id=pref_id, user_id=user_id)
    return True


async def bulk_update_prefs(
    db: AsyncSession,
    user_id: int,
    updates: list[dict],
) -> int:
    """Update multiple notification preferences in one batch.

    Upserts preferences based on (channel, event_type) uniqueness.

    Args:
        db: Async session bound to the application database.
        user_id: Owner user ID.
        updates: List of dicts, each with at least 'channel' and 'event_type'.

    Returns:
        Number of preferences updated or created.
    """
    created = 0
    for item in updates:
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.channel == item["channel"],
                NotificationPreference.event_type == item["event_type"],
            )
        )
        pref = result.scalar_one_or_none()

        if pref is None:
            pref = NotificationPreference(
                user_id=user_id,
                channel=item["channel"],
                event_type=item["event_type"],
                enabled=item.get("enabled", True),
                config=item.get("config"),
            )
            db.add(pref)
            created += 1
        else:
            if "enabled" in item:
                pref.enabled = item["enabled"]
            if "config" in item:
                pref.config = item["config"]

    await db.commit()
    logger.info("notification.bulk_updated", user_id=user_id, count=created + len(updates))
    return created + len(updates)
