"""User notification preference management."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.notification import NotificationPreference
from app.schemas.common import MessageResponse
from app.schemas.notification import NotificationPrefRequest, NotificationPrefResponse
from app.services.notifications import prefs as prefs_svc

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/prefs", response_model=list[NotificationPrefResponse])
async def list_prefs(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[NotificationPrefResponse]:
    """Return the current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.user_id,
            NotificationPreference.org_id == current_user.org_id,
        )
    )
    return [NotificationPrefResponse.model_validate(p) for p in result.scalars().all()]


@router.put("/prefs/{pref_id}", response_model=MessageResponse)
async def update_pref(
    pref_id: int,
    data: NotificationPrefRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Update a notification preference."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.id == pref_id,
            NotificationPreference.user_id == current_user.user_id,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    pref.enabled = data.enabled
    pref.config = data.config
    await db.commit()
    logger.info("notification.pref_updated", pref_id=pref_id)
    return MessageResponse(message="Preference updated")


@router.put("/prefs/bulk", response_model=MessageResponse)
async def bulk_update_prefs(
    data: list[dict],
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Bulk update notification preferences."""
    count = await prefs_svc.bulk_update_prefs(db, current_user.user_id, data)
    return MessageResponse(message=f"{count} preferences updated")
