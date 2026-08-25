"""Audit log helper — add a single-call function for consistent audit entries.

All state-mutating actions should record an AuditLog row via audit_action()
before (or inside) the same DB commit that makes the change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def audit_action(
    db: AsyncSession,
    *,
    org_id: int,
    user_id: int | None,
    action: str,
    resource_type: str | None = None,
    resource_id: int | None = None,
    resource_name: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Add an AuditLog row to the current DB session.

    The caller is responsible for committing. Failures are silent so that an
    audit error never blocks the actual operation — structlog captures the
    exception at the INFO level.

    Args:
        db: Async SQLAlchemy session.
        org_id: Organisation the action belongs to.
        user_id: User who performed the action (None for system actions).
        action: Dot-separated action name, e.g. ``"erd.generated"``.
        resource_type: Kind of object affected, e.g. ``"erd"``.
        resource_id: Integer primary-key of the affected object.
        resource_name: Human-readable name (supplement to resource_id).
        ip_address: Client IP, forwarded from the request if available.
        user_agent: Client User-Agent header if available.
        extra: Any additional structured context.
    """
    from app.models.audit import AuditLog  # noqa: PLC0415

    db.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            ip_address=ip_address,
            user_agent=user_agent,
            extra=extra,
        )
    )
