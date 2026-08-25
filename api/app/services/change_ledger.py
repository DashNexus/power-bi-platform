"""Universal change ledger: snapshot hook + revert engine.

Every create/update/delete on a first-class resource records a ``ChangeLedgerEntry``
with a full before/after snapshot of the row. The ``log_*`` helpers mirror
``services.audit.audit_action`` — they add a row to the caller's session, the
caller commits, and failures are swallowed so logging never blocks the mutation.

The revert engine undoes a recorded change (or a correlated group of changes) by
re-applying the opposite operation from the stored snapshots. It is authorization
agnostic: callers (``routers/changes.py``) enforce access before invoking it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import Date, DateTime, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import TypeEngine

from app.models.change_ledger import ChangeLedgerEntry

if TYPE_CHECKING:
    from app.middleware.auth import CurrentUser
    from app.models.base import Base
    from app.services.mutation_registry import MutationResource

logger = structlog.get_logger(__name__)


class RevertConflictError(Exception):
    """The change cannot be reverted in the current state (maps to HTTP 409)."""


class RevertUnavailableError(Exception):
    """The change is not revertible (unknown resource type; maps to HTTP 422)."""


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _coerce(value: Any) -> Any:  # noqa: ANN401 — serialises arbitrary column values
    """Coerce a column value into a JSON-serialisable form."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def serialize_row(obj: Base) -> dict[str, Any]:
    """Return a JSON-safe dict of a mapped row's scalar columns (no relationships).

    Returns an empty dict if the object cannot be introspected, so a snapshot
    never blocks the mutation it accompanies.
    """
    try:
        mapper = sa_inspect(type(obj)).mapper
    except Exception:  # noqa: BLE001 — non-mapped object (e.g. a test double)
        return {}
    return {attr.key: _coerce(getattr(obj, attr.key)) for attr in mapper.column_attrs}


def _column_types(model: type[Base]) -> dict[str, TypeEngine[Any]]:
    """Map each scalar attribute name to its SQLAlchemy column type."""
    mapper = sa_inspect(model).mapper
    return {attr.key: attr.columns[0].type for attr in mapper.column_attrs}


def _deserialize(col_type: TypeEngine[Any], value: Any) -> Any:  # noqa: ANN401 — round-trips snapshot values
    """Convert a JSON snapshot value back into a Python value for its column type."""
    if value is None:
        return None
    if isinstance(col_type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(col_type, Date) and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return value


# Columns the database maintains rather than the caller. `updated_at` carries
# onupdate=func.now(), which SQL evaluates at flush — *after* log_update has
# snapshotted the row — so the stored `after` can never equal the committed value.
# Comparing it would make the optimistic-concurrency check below reject every
# update revert with a spurious 409, on every model carrying TimestampMixin.
_SERVER_MANAGED_COLUMNS = frozenset({"created_at", "updated_at"})


def _comparable(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Return a snapshot reduced to the fields a caller can actually have changed."""
    return {k: v for k, v in (snapshot or {}).items() if k not in _SERVER_MANAGED_COLUMNS}


def compute_diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return per-field {field, old, new} entries for the changed columns."""
    before = before or {}
    after = after or {}
    diff: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            diff.append({"field": key, "old": old, "new": new})
    return diff


# ---------------------------------------------------------------------------
# Logging context + hook
# ---------------------------------------------------------------------------


def new_correlation_id() -> str:
    """Return a fresh correlation id grouping the changes of one logical action."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class LedgerContext:
    """Who/what is making a change, and the group it belongs to."""

    org_id: int
    actor_user_id: int | None
    source: str = "user"
    correlation_id: str = field(default_factory=new_correlation_id)


def ctx_for(
    current_user: CurrentUser,
    *,
    source: str = "user",
    correlation_id: str | None = None,
) -> LedgerContext:
    """Build a LedgerContext from the authenticated user."""
    return LedgerContext(
        org_id=current_user.org_id,
        actor_user_id=current_user.user_id,
        source=source,
        correlation_id=correlation_id or new_correlation_id(),
    )


def _add_entry(
    db: AsyncSession,
    ctx: LedgerContext,
    *,
    resource_type: str,
    resource_id: int | None,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    resource_name: str | None,
) -> None:
    db.add(
        ChangeLedgerEntry(
            org_id=ctx.org_id,
            correlation_id=ctx.correlation_id,
            actor_user_id=ctx.actor_user_id,
            source=ctx.source,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            before=before,
            after=after,
            resource_name=resource_name,
        )
    )


async def log_create(
    db: AsyncSession,
    *,
    ctx: LedgerContext,
    resource_type: str,
    obj: Base,
    resource_name: str | None = None,
) -> None:
    """Record a create. Call after the row has been flushed (so it has an id)."""
    try:
        _add_entry(
            db,
            ctx,
            resource_type=resource_type,
            resource_id=getattr(obj, "id", None),
            action="create",
            before=None,
            after=serialize_row(obj),
            resource_name=resource_name,
        )
    except Exception as exc:  # noqa: BLE001 — logging must never block the mutation
        logger.warning(
            "change_ledger.log_create_failed", resource_type=resource_type, error=str(exc)
        )


async def log_update(
    db: AsyncSession,
    *,
    ctx: LedgerContext,
    resource_type: str,
    obj: Base,
    before: dict[str, Any],
    resource_name: str | None = None,
) -> None:
    """Record an update. ``before`` must be a snapshot taken before the mutation."""
    try:
        _add_entry(
            db,
            ctx,
            resource_type=resource_type,
            resource_id=getattr(obj, "id", None),
            action="update",
            before=before,
            after=serialize_row(obj),
            resource_name=resource_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "change_ledger.log_update_failed", resource_type=resource_type, error=str(exc)
        )


async def log_delete(
    db: AsyncSession,
    *,
    ctx: LedgerContext,
    resource_type: str,
    obj: Base,
    resource_name: str | None = None,
) -> None:
    """Record a delete. Call before ``db.delete(obj)`` so the snapshot is complete."""
    try:
        _add_entry(
            db,
            ctx,
            resource_type=resource_type,
            resource_id=getattr(obj, "id", None),
            action="delete",
            before=serialize_row(obj),
            after=None,
            resource_name=resource_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "change_ledger.log_delete_failed", resource_type=resource_type, error=str(exc)
        )


# ---------------------------------------------------------------------------
# Revert engine
# ---------------------------------------------------------------------------


def _get_resource(resource_type: str) -> MutationResource:
    from app.services.mutation_registry import get_resource  # noqa: PLC0415

    resource = get_resource(resource_type)
    if resource is None:
        raise RevertUnavailableError(f"'{resource_type}' changes cannot be reverted.")
    return resource


async def _load(
    db: AsyncSession, model: type[Base], org_id: int, resource_id: int | None
) -> Base | None:
    if resource_id is None:
        return None
    stmt = select(model).where(model.id == resource_id)  # type: ignore[attr-defined]
    if hasattr(model, "org_id"):
        stmt = stmt.where(model.org_id == org_id)  # type: ignore[attr-defined]
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _instantiate(
    model: type[Base],
    data: dict[str, Any],
    col_types: dict[str, TypeEngine[Any]],
    *,
    skip: tuple[str, ...] = ("id",),
) -> Base:
    kwargs = {
        name: _deserialize(col_types[name], data[name])
        for name in col_types
        if name in data and name not in skip
    }
    return model(**kwargs)


@dataclass
class RevertResult:
    """Outcome of reverting one ledger entry."""

    ledger_id: int
    resource_type: str
    inverse_action: str
    resource_id: int | None


async def _revert_one(
    db: AsyncSession,
    entry: ChangeLedgerEntry,
    *,
    force: bool,
    id_maps: dict[str, dict[int, int]] | None = None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, int | None]:
    """Apply the inverse of one entry. Returns (inverse_action, before, after, id)."""
    resource = _get_resource(entry.resource_type)
    model = resource.model
    col_types = _column_types(model)

    if entry.action == "create":
        current = await _load(db, model, entry.org_id, entry.resource_id)
        before_snap = serialize_row(current) if current is not None else entry.after
        if current is not None:
            # Some resources acquire children holding a NO ACTION foreign key
            # after they are created (a report gains runs), and the delete fails
            # until the link is cleared. The descriptor supplies that step.
            if resource.pre_delete is not None:
                await resource.pre_delete(db, current)
            await db.delete(current)
        return "delete", before_snap, None, entry.resource_id

    if entry.action == "update":
        current = await _load(db, model, entry.org_id, entry.resource_id)
        if current is None:
            raise RevertConflictError("The target no longer exists.")
        if not force and _comparable(serialize_row(current)) != _comparable(entry.after):
            raise RevertConflictError(
                "The record changed since this version; revert with force to override."
            )
        pre = serialize_row(current)
        for name, col_type in col_types.items():
            if name == "id" or name in _SERVER_MANAGED_COLUMNS:
                continue
            if entry.before and name in entry.before:
                setattr(current, name, _deserialize(col_type, entry.before[name]))
        return "update", pre, serialize_row(current), current.id

    # entry.action == "delete" — recreate the row.
    instance = _instantiate(model, entry.before or {}, col_types)
    if id_maps:
        for col, parent_type in resource.parent_fks.items():
            old = getattr(instance, col, None)
            if old is not None and old in id_maps.get(parent_type, {}):
                setattr(instance, col, id_maps[parent_type][old])
    db.add(instance)
    await db.flush()
    return "create", None, serialize_row(instance), instance.id


def _record_inverse(
    db: AsyncSession,
    entry: ChangeLedgerEntry,
    *,
    actor_user_id: int | None,
    inverse_action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    resource_id: int | None,
) -> None:
    entry.reverted_at = func.now()
    entry.reverted_by_user_id = actor_user_id
    db.add(
        ChangeLedgerEntry(
            org_id=entry.org_id,
            correlation_id=entry.correlation_id,
            actor_user_id=actor_user_id,
            source="user",
            resource_type=entry.resource_type,
            resource_id=resource_id,
            action=inverse_action,
            before=before,
            after=after,
            resource_name=entry.resource_name,
            revert_of_id=entry.id,
        )
    )


async def revert_entry(
    db: AsyncSession,
    entry: ChangeLedgerEntry,
    *,
    actor_user_id: int | None,
    force: bool = False,
) -> RevertResult:
    """Revert a single ledger entry. Caller enforces access and commits."""
    if entry.reverted_at is not None:
        raise RevertConflictError("This change has already been reverted.")
    try:
        inverse_action, before, after, resource_id = await _revert_one(db, entry, force=force)
    except IntegrityError as exc:
        raise RevertConflictError("Reverting would violate a data constraint.") from exc
    _record_inverse(
        db,
        entry,
        actor_user_id=actor_user_id,
        inverse_action=inverse_action,
        before=before,
        after=after,
        resource_id=resource_id,
    )
    return RevertResult(entry.id, entry.resource_type, inverse_action, resource_id)


async def revert_correlation(
    db: AsyncSession,
    entries: list[ChangeLedgerEntry],
    *,
    actor_user_id: int | None,
    force: bool = False,
) -> list[RevertResult]:
    """Revert a correlated group as a unit. Caller enforces access and commits.

    Creates are undone (deleted) children-first; deletes are undone (recreated)
    parents-first with child foreign keys remapped to the newly-assigned ids.
    """
    pending = [e for e in entries if e.reverted_at is None]
    if not pending:
        raise RevertConflictError("These changes have already been reverted.")

    creates = sorted(
        (e for e in pending if e.action == "create"), key=lambda e: e.id, reverse=True
    )
    updates = [e for e in pending if e.action == "update"]
    deletes = sorted((e for e in pending if e.action == "delete"), key=lambda e: e.id)

    id_maps: dict[str, dict[int, int]] = {}
    results: list[RevertResult] = []
    try:
        for entry in [*creates, *updates, *deletes]:
            inverse_action, before, after, resource_id = await _revert_one(
                db, entry, force=force, id_maps=id_maps
            )
            if entry.action == "delete" and entry.before and resource_id is not None:
                old_id = entry.before.get("id")
                if isinstance(old_id, int):
                    id_maps.setdefault(entry.resource_type, {})[old_id] = resource_id
            _record_inverse(
                db,
                entry,
                actor_user_id=actor_user_id,
                inverse_action=inverse_action,
                before=before,
                after=after,
                resource_id=resource_id,
            )
            results.append(
                RevertResult(entry.id, entry.resource_type, inverse_action, resource_id)
            )
    except IntegrityError as exc:
        raise RevertConflictError("Reverting would violate a data constraint.") from exc
    except SQLAlchemyError as exc:
        raise RevertConflictError(f"Revert failed: {exc}") from exc

    await _remap_json_ids(db, pending, id_maps)
    return results


async def _remap_json_ids(
    db: AsyncSession, entries: list[ChangeLedgerEntry], id_maps: dict[str, dict[int, int]]
) -> None:
    """Let restored rows follow ids that changed while recreating the group.

    Runs after every row is back, because a row restored early (an update
    revert) can reference one recreated later (a delete revert). Real foreign
    keys are handled by ``parent_fks``; this covers references a JSON column
    merely contains, such as the nav config's ``/dashboard/{id}`` hrefs.
    """
    if not id_maps:
        return
    for entry in entries:
        resource = _get_resource(entry.resource_type)
        if resource.remap_ids is None:
            continue
        row = await _load(db, resource.model, entry.org_id, entry.resource_id)
        if row is not None:
            resource.remap_ids(row, id_maps)
