"""Audit log: filtered reads, retention policy, and purge.

Separate from the change ledger (`routers/changes.py`): the audit log records
*that* something happened, the ledger records the before/after needed to undo it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser
from app.models.audit import AuditLog
from app.models.org_settings import OrgSettings
from app.models.user import User
from app.services.permissions import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter()

# Admins hold every permission key, so these also pass admins.
_view_dep = require_permission("audit.view", "audit.manage")
_manage_dep = require_permission("audit.manage")


@router.get("")
async def get_audit_log(
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    user_email: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    resource_type: str | None = None,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Return a filtered, paginated audit log of user actions for the organisation.

    Args:
        page: 1-indexed page number.
        page_size: Entries per page (max 200).
        action: Filter to entries whose action starts with this prefix (e.g. "user").
        user_email: Filter to entries from this user email (partial, case-insensitive).
        from_date: ISO date string — only entries on or after this date.
        to_date: ISO date string — only entries on or before this date.
        resource_type: Filter by exact resource_type value.
        current_user: Authenticated principal, org-scoping the query.
        db: Application database session.

    Returns:
        Paginated list of audit log entries with user, action, and timestamp.
    """
    page_size = min(page_size, 200)
    offset = (page - 1) * page_size

    conditions = [AuditLog.org_id == current_user.org_id]

    if action:
        conditions.append(AuditLog.action.like(f"{action}%"))
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if from_date:
        try:
            conditions.append(
                AuditLog.created_at >= datetime.fromisoformat(from_date).replace(tzinfo=UTC)
            )
        except ValueError:
            pass
    if to_date:
        try:
            conditions.append(
                AuditLog.created_at <= datetime.fromisoformat(to_date).replace(tzinfo=UTC)
            )
        except ValueError:
            pass

    base_query = (
        select(AuditLog, User.email, User.display_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(and_(*conditions))
    )
    if user_email:
        base_query = base_query.where(User.email.ilike(f"%{user_email}%"))

    total = (
        await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
    ).scalar_one()

    rows_result = await db.execute(
        base_query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
    )

    entries = [
        {
            "id": log.id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "resource_name": log.resource_name,
            "user_email": email,
            "user_name": display_name,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat(),
        }
        for log, email, display_name in rows_result.all()
    ]

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/retention")
async def get_audit_retention(
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Return the current audit log retention policy for the organisation."""
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == current_user.org_id))
    ).scalar_one_or_none()
    return {"audit_retention_days": row.audit_retention_days if row else None}


@router.put("/retention")
async def update_audit_retention(
    data: dict,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Set or clear the audit log retention period for the organisation.

    When audit_retention_days is set, older entries can be purged by calling
    POST /audit/retention/purge. A null value disables auto-purge.
    """
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == current_user.org_id))
    ).scalar_one_or_none()
    if row is None:
        row = OrgSettings(org_id=current_user.org_id)
        db.add(row)
    days = data.get("audit_retention_days")
    row.audit_retention_days = int(days) if days is not None else None
    await db.commit()
    return {"audit_retention_days": row.audit_retention_days}


@router.post("/retention/purge")
async def purge_audit_log(
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Delete audit entries older than the configured retention period.

    No-ops when retention is not configured (null). Returns the number of
    entries deleted.
    """
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == current_user.org_id))
    ).scalar_one_or_none()
    if row is None or row.audit_retention_days is None:
        return {"deleted": 0, "message": "No retention policy configured."}

    cutoff = datetime.now(UTC) - timedelta(days=row.audit_retention_days)
    del_result = await db.execute(
        sa_delete(AuditLog).where(
            AuditLog.org_id == current_user.org_id,
            AuditLog.created_at < cutoff,
        )
    )
    await db.commit()
    deleted = del_result.rowcount
    logger.info("audit.purge", org_id=current_user.org_id, deleted=deleted, cutoff=cutoff)
    return {
        "deleted": deleted,
        "message": f"Deleted {deleted} entries older than {row.audit_retention_days} days.",
    }
