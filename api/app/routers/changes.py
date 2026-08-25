"""Change-history feeds and revert endpoints backed by the universal ledger.

Per-resource history and revert reuse each resource's existing view/edit guards
(via the mutation registry); the cross-resource global feed is gated by the
``changes.view`` permission (admins bypass).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.change_ledger import ChangeLedgerEntry
from app.models.user import User
from app.services import change_ledger
from app.services.audit import audit_action
from app.services.mutation_registry import get_resource, top_level_resources

logger = structlog.get_logger(__name__)

router = APIRouter()

# Change-ledger entries are retained for 90 days; older rows are purged lazily
# whenever the global feed is loaded (a cheap indexed DELETE that usually
# affects nothing) and can be triggered explicitly via POST /changes/purge.
RETENTION_DAYS = 90


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ChangeRecord(BaseModel):
    """One ledger entry rendered for the UI."""

    id: int
    correlation_id: str
    resource_type: str
    resource_id: int | None
    resource_name: str | None
    action: str
    source: str
    actor_name: str | None
    created_at: datetime
    reverted_at: datetime | None
    diff: list[dict[str, Any]]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    # How many entries share this correlation id. > 1 means the action touched
    # several rows and has to be reverted as a group to come back intact.
    correlation_size: int


class ResourceTypeOption(BaseModel):
    """One entry in the feed's resource-type filter menu."""

    value: str
    label: str


class RevertItem(BaseModel):
    """One reverted entry in a revert response."""

    ledger_id: int
    resource_type: str
    inverse_action: str
    resource_id: int | None


class RevertResponse(BaseModel):
    """Result of a revert (single or grouped)."""

    reverted: list[RevertItem]


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


async def _require_changes_view(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> CurrentUser:
    """Allow admins, or any user holding the changes.view permission."""
    if current_user.role in ("admin", "superadmin"):
        return current_user
    from app.services.permissions import user_has_permission  # noqa: PLC0415

    if await user_has_permission(db, current_user, "changes.view"):
        return current_user
    raise HTTPException(status_code=403, detail="You do not have access to the change history")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _actor_names(db: AsyncSession, entries: list[ChangeLedgerEntry]) -> dict[int, str]:
    """Map actor user ids present in ``entries`` to a display name."""
    ids = {e.actor_user_id for e in entries if e.actor_user_id is not None}
    if not ids:
        return {}
    result = await db.execute(
        select(User.id, User.display_name, User.email).where(User.id.in_(ids))
    )
    return {row[0]: (row[1] or row[2] or f"User {row[0]}") for row in result.all()}


async def _correlation_sizes(
    db: AsyncSession, org_id: int, entries: list[ChangeLedgerEntry]
) -> dict[str, int]:
    """Count how many ledger rows belong to each correlation id in ``entries``."""
    ids = {e.correlation_id for e in entries}
    if not ids:
        return {}
    result = await db.execute(
        select(ChangeLedgerEntry.correlation_id, func.count(ChangeLedgerEntry.id))
        .where(
            ChangeLedgerEntry.org_id == org_id,
            ChangeLedgerEntry.correlation_id.in_(ids),
        )
        .group_by(ChangeLedgerEntry.correlation_id)
    )
    return {row[0]: row[1] for row in result.all()}


def _to_record(
    entry: ChangeLedgerEntry, actor_names: dict[int, str], sizes: dict[str, int]
) -> ChangeRecord:
    return ChangeRecord(
        id=entry.id,
        correlation_id=entry.correlation_id,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        resource_name=entry.resource_name,
        action=entry.action,
        source=entry.source,
        actor_name=actor_names.get(entry.actor_user_id) if entry.actor_user_id else None,
        created_at=entry.created_at,
        reverted_at=entry.reverted_at,
        diff=change_ledger.compute_diff(entry.before, entry.after),
        before=entry.before,
        after=entry.after,
        correlation_size=sizes.get(entry.correlation_id, 1),
    )


def _snapshot(entry: ChangeLedgerEntry) -> dict[str, Any] | None:
    return entry.after or entry.before


# ---------------------------------------------------------------------------
# Element history
# ---------------------------------------------------------------------------


@router.get("/changes/{resource_type}/{resource_id}", response_model=list[ChangeRecord])
async def element_history(
    resource_type: str,
    resource_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[ChangeRecord]:
    """Return the change history for one element, newest first.

    Access mirrors the resource's own view permission.
    """
    resource = get_resource(resource_type)
    if resource is None:
        raise HTTPException(status_code=422, detail=f"Unknown resource type '{resource_type}'")

    result = await db.execute(
        select(ChangeLedgerEntry)
        .where(
            ChangeLedgerEntry.org_id == current_user.org_id,
            ChangeLedgerEntry.resource_type == resource_type,
            ChangeLedgerEntry.resource_id == resource_id,
        )
        .order_by(ChangeLedgerEntry.created_at.desc(), ChangeLedgerEntry.id.desc())
    )
    entries = list(result.scalars().all())

    snapshot = _snapshot(entries[0]) if entries else None
    await resource.require_view(db, current_user, resource_id, snapshot)

    actor_names = await _actor_names(db, entries)
    sizes = await _correlation_sizes(db, current_user.org_id, entries)
    return [_to_record(e, actor_names, sizes) for e in entries]


# ---------------------------------------------------------------------------
# Global feeds
# ---------------------------------------------------------------------------


async def _purge_expired(db: AsyncSession, org_id: int) -> None:
    """Delete this org's change-ledger entries older than the retention window."""
    from datetime import timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    await db.execute(
        delete(ChangeLedgerEntry).where(
            ChangeLedgerEntry.org_id == org_id, ChangeLedgerEntry.created_at < cutoff
        )
    )
    await db.commit()


async def _actor_ids_matching(db: AsyncSession, org_id: int, query: str) -> list[int]:
    """Return user ids whose name or email matches the search query (case-insensitive)."""
    like = f"%{query.strip()}%"
    result = await db.execute(
        select(User.id).where(
            User.org_id == org_id,
            or_(User.display_name.ilike(like), User.email.ilike(like)),
        )
    )
    return [row[0] for row in result.all()]


async def _feed(
    db: AsyncSession,
    org_id: int,
    *,
    source: str | None,
    resource_type: str | None,
    action: str | None,
    actor_user_id: int | None,
    actor: str | None,
    correlation_id: str | None,
    limit: int,
    offset: int,
) -> list[ChangeRecord]:
    stmt = select(ChangeLedgerEntry).where(ChangeLedgerEntry.org_id == org_id)
    if source:
        stmt = stmt.where(ChangeLedgerEntry.source == source)
    if resource_type:
        stmt = stmt.where(ChangeLedgerEntry.resource_type == resource_type)
    if action:
        stmt = stmt.where(ChangeLedgerEntry.action == action)
    if actor_user_id is not None:
        stmt = stmt.where(ChangeLedgerEntry.actor_user_id == actor_user_id)
    if actor:
        matching = await _actor_ids_matching(db, org_id, actor)
        # No matching users → no rows (an empty IN would match everything otherwise).
        stmt = stmt.where(ChangeLedgerEntry.actor_user_id.in_(matching or [-1]))
    if correlation_id:
        stmt = stmt.where(ChangeLedgerEntry.correlation_id == correlation_id)
    stmt = stmt.order_by(
        ChangeLedgerEntry.created_at.desc(), ChangeLedgerEntry.id.desc()
    ).limit(limit).offset(offset)

    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    actor_names = await _actor_names(db, entries)
    sizes = await _correlation_sizes(db, org_id, entries)
    return [_to_record(e, actor_names, sizes) for e in entries]


@router.get("/changes/resource-types", response_model=list[ResourceTypeOption])
async def list_resource_types(
    _current_user: CurrentUser = Depends(_require_changes_view),
) -> list[ResourceTypeOption]:
    """Return the resource types the feed can be filtered by.

    Served from the mutation registry rather than restated in the client: the
    filter menu on `/admin/changes` was a hand-written list inherited from a
    build with different resources, so it offered types that do not exist here
    and omitted the ones that do.
    """
    return [ResourceTypeOption(value=value, label=label) for value, label in top_level_resources()]


@router.get("/changes", response_model=list[ChangeRecord])
async def global_feed(
    source: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    actor: str | None = Query(default=None),
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(_require_changes_view),
    db: AsyncSession = Depends(get_app_db),
) -> list[ChangeRecord]:
    """Return the org-wide change feed with optional filters.

    Enforces the 90-day retention window by purging expired rows on load.
    """
    await _purge_expired(db, current_user.org_id)
    return await _feed(
        db,
        current_user.org_id,
        source=source,
        resource_type=resource_type,
        action=action,
        actor_user_id=actor_user_id,
        actor=actor,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )


@router.post("/changes/purge")
async def purge_changes(
    current_user: CurrentUser = Depends(_require_changes_view),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Manually purge change-ledger entries older than the retention window."""
    await _purge_expired(db, current_user.org_id)
    return {"status": "purged", "retention_days": str(RETENTION_DAYS)}


def _translate_revert_error(exc: Exception) -> HTTPException:
    if isinstance(exc, change_ledger.RevertConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, change_ledger.RevertUnavailableError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Revert failed")


@router.post("/changes/{ledger_id}/revert", response_model=RevertResponse)
async def revert_change(
    ledger_id: int,
    force: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> RevertResponse:
    """Revert a single ledger entry (requires edit access to the resource)."""
    result = await db.execute(
        select(ChangeLedgerEntry).where(
            ChangeLedgerEntry.id == ledger_id,
            ChangeLedgerEntry.org_id == current_user.org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Change not found")

    resource = get_resource(entry.resource_type)
    if resource is None:
        raise HTTPException(status_code=422, detail=f"'{entry.resource_type}' cannot be reverted")
    await resource.require_edit(db, current_user, entry.resource_id, _snapshot(entry))

    try:
        outcome = await change_ledger.revert_entry(
            db, entry, actor_user_id=current_user.user_id, force=force
        )
    except (change_ledger.RevertConflictError, change_ledger.RevertUnavailableError) as exc:
        await db.rollback()
        raise _translate_revert_error(exc) from exc

    await audit_action(
        db,
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="change.reverted",
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        resource_name=entry.resource_name,
        extra={"ledger_id": entry.id, "correlation_id": entry.correlation_id},
    )
    await db.commit()
    return RevertResponse(
        reverted=[
            RevertItem(
                ledger_id=outcome.ledger_id,
                resource_type=outcome.resource_type,
                inverse_action=outcome.inverse_action,
                resource_id=outcome.resource_id,
            )
        ]
    )


@router.post("/changes/correlation/{correlation_id}/revert", response_model=RevertResponse)
async def revert_correlation(
    correlation_id: str,
    force: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> RevertResponse:
    """Revert every change in a correlated action (requires edit on each resource)."""
    result = await db.execute(
        select(ChangeLedgerEntry)
        .where(
            ChangeLedgerEntry.org_id == current_user.org_id,
            ChangeLedgerEntry.correlation_id == correlation_id,
        )
        .order_by(ChangeLedgerEntry.id)
    )
    entries = list(result.scalars().all())
    if not entries:
        raise HTTPException(status_code=404, detail="No changes found for this action")

    # Every touched resource must be edit-accessible before any revert runs.
    for entry in entries:
        resource = get_resource(entry.resource_type)
        if resource is None:
            raise HTTPException(
                status_code=422, detail=f"'{entry.resource_type}' cannot be reverted"
            )
        await resource.require_edit(db, current_user, entry.resource_id, _snapshot(entry))

    try:
        outcomes = await change_ledger.revert_correlation(
            db, entries, actor_user_id=current_user.user_id, force=force
        )
    except (change_ledger.RevertConflictError, change_ledger.RevertUnavailableError) as exc:
        await db.rollback()
        raise _translate_revert_error(exc) from exc

    await audit_action(
        db,
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="change.reverted_group",
        resource_type=entries[0].resource_type,
        resource_name=entries[0].resource_name,
        extra={"correlation_id": correlation_id, "count": len(outcomes)},
    )
    await db.commit()
    return RevertResponse(
        reverted=[
            RevertItem(
                ledger_id=o.ledger_id,
                resource_type=o.resource_type,
                inverse_action=o.inverse_action,
                resource_id=o.resource_id,
            )
            for o in outcomes
        ]
    )
