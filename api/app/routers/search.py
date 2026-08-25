"""Cross-resource search endpoint."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.dashboard import DashboardConfig
from app.models.page import CustomPage
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("")
async def search(
    q: str = "",
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, object]:
    """Search dashboards and pages by name or title.

    Returns up to 5 results per resource type. Requires at least 2 characters.

    Args:
        q: Search query string.

    Returns:
        Dict with 'results' list and the echoed 'query'.
    """
    if len(q.strip()) < 2:
        return {"results": [], "query": q}

    term = f"%{q.strip().lower()}%"
    results: list[dict[str, object]] = []

    # Dashboards
    dash_rows = await db.execute(
        select(DashboardConfig)
        .where(
            DashboardConfig.org_id == current_user.org_id,
            is_true(DashboardConfig.is_active),
            or_(
                func.lower(DashboardConfig.name).like(term),
                func.lower(DashboardConfig.description).like(term),
            ),
        )
        .order_by(DashboardConfig.name)
        .limit(5)
    )
    for d in dash_rows.scalars().all():
        results.append(
            {
                "type": "dashboard",
                "id": d.id,
                "title": d.name,
                "description": d.description,
                "href": f"/dashboard/{d.id}",
                "label": d.embed_type,
            }
        )

    # Pages
    page_rows = await db.execute(
        select(CustomPage)
        .where(
            CustomPage.org_id == current_user.org_id,
            is_true(CustomPage.is_published),
            or_(
                func.lower(CustomPage.title).like(term),
                func.lower(CustomPage.slug).like(term),
            ),
        )
        .order_by(CustomPage.title)
        .limit(5)
    )
    for p in page_rows.scalars().all():
        results.append(
            {
                "type": "page",
                "id": p.id,
                "title": p.title,
                "description": f"/{p.slug}",
                "href": f"/pages/{p.slug}",
                "label": "Page",
            }
        )

    logger.debug("search.query", q=q, result_count=len(results))
    return {"results": results, "query": q}
