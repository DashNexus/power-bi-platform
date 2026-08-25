"""User favorites management endpoints."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.favorite import UserFavorite

logger = structlog.get_logger(__name__)

router = APIRouter()

# Must match the resource_type strings the frontend sends (PortalHomeClient and
# the per-resource listing pages) — e.g. "data_dictionary", not "data_dict".
_VALID_RESOURCE_TYPES = {
    "dashboard",
    "page",
    "data_dictionary",
    "data_pipeline",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FavoriteCreateRequest(BaseModel):
    """Payload for adding a resource to the current user's favorites."""

    resource_type: str  # 'dashboard' | 'page' | 'data_dictionary' | 'data_pipeline'
    resource_id: int


class FavoriteResponse(BaseModel):
    """A single user favorite."""

    id: int
    resource_type: str
    resource_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/favorites", response_model=list[FavoriteResponse])
async def list_favorites(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[FavoriteResponse]:
    """Return all favorites for the authenticated user."""
    result = await db.execute(
        select(UserFavorite).where(UserFavorite.user_id == current_user.user_id)
    )
    return [FavoriteResponse.model_validate(f) for f in result.scalars().all()]


@router.post("/favorites", response_model=FavoriteResponse, status_code=201)
async def add_favorite(
    data: FavoriteCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> FavoriteResponse:
    """Add a resource to the current user's favorites.

    Args:
        data: resource_type (see _VALID_RESOURCE_TYPES) and resource_id.
    """
    if data.resource_type not in _VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"resource_type must be one of: {', '.join(sorted(_VALID_RESOURCE_TYPES))}",
        )

    existing = await db.execute(
        select(UserFavorite).where(
            UserFavorite.user_id == current_user.user_id,
            UserFavorite.resource_type == data.resource_type,
            UserFavorite.resource_id == data.resource_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Already in favorites")

    fav = UserFavorite(
        user_id=current_user.user_id,
        org_id=current_user.org_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
    )
    db.add(fav)
    await db.commit()
    await db.refresh(fav)

    logger.info(
        "favorites.added",
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        user_id=current_user.user_id,
    )
    return FavoriteResponse.model_validate(fav)


@router.delete("/favorites/{resource_type}/{resource_id}", status_code=204)
async def remove_favorite(
    resource_type: str,
    resource_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Remove a resource from the current user's favorites.

    Args:
        resource_type: One of _VALID_RESOURCE_TYPES.
        resource_id: Primary key of the resource.
    """
    result = await db.execute(
        select(UserFavorite).where(
            UserFavorite.user_id == current_user.user_id,
            UserFavorite.resource_type == resource_type,
            UserFavorite.resource_id == resource_id,
        )
    )
    fav = result.scalar_one_or_none()
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite not found")

    await db.delete(fav)
    await db.commit()

    logger.info(
        "favorites.removed",
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=current_user.user_id,
    )
