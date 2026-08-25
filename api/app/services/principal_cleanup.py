"""Detach a user or role from every row referencing it, before deleting it.

This exists because the schema has to be creatable on Azure SQL. SQL Server
rejects a foreign key that introduces a second *cascading action* — CASCADE and
SET NULL alike — between the same two tables (error 1785), and PostgreSQL does
not. Rather than let the two engines delete different rows, every table keeps
exactly one CASCADE parent, every attribution column is plain NO ACTION, and the
difference is made explicit here.

Two kinds of reference, handled differently:

* **Grants** name a principal in order to give it access. With the principal
  gone the row means nothing, so it is deleted.
* **Attribution** ("created by", "acted as") records who did something. The
  record outlives the account, so the pointer is nulled and the row kept —
  deleting audit or change-ledger history to delete a user would be the wrong
  trade entirely.

**Every path that deletes a user or a role must call these first**, or the
delete fails on a foreign key. That loud failure is the intended mode: a
silently orphaned grant hands access to whoever is assigned the recycled id.
"""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.change_ledger import ChangeLedgerEntry
from app.models.dashboard import DashboardConfig, DashboardConfigVersion, DashboardPermission
from app.models.data_dict import DataDictionaryPermission
from app.models.data_pipeline import DataPipelineConnectionPermission
from app.models.feature_flag import FeatureFlag
from app.models.page import CustomPage, CustomPagePermission, CustomPageVersion
from app.models.user import UserInvite, UserRole
from app.models.warehouse import WarehouseConnectionPermission

#: Per-resource grants. Deleted outright — a grant to nobody is not a grant.
_GRANT_TABLES = (
    DashboardPermission,
    CustomPagePermission,
    DataDictionaryPermission,
    WarehouseConnectionPermission,
    DataPipelineConnectionPermission,
)

#: (model, column) pairs recording *who did something*. Nulled, never deleted.
_USER_ATTRIBUTION = (
    (AuditLog, AuditLog.user_id),
    (ChangeLedgerEntry, ChangeLedgerEntry.actor_user_id),
    (ChangeLedgerEntry, ChangeLedgerEntry.reverted_by_user_id),
    (CustomPage, CustomPage.created_by_user_id),
    (CustomPageVersion, CustomPageVersion.created_by_user_id),
    (DashboardConfig, DashboardConfig.created_by_user_id),
    (DashboardConfigVersion, DashboardConfigVersion.created_by_user_id),
    (FeatureFlag, FeatureFlag.updated_by_user_id),
    (UserInvite, UserInvite.created_by_user_id),
)


async def remove_user_grants(db: AsyncSession, user_id: int) -> None:
    """Detach a user from every row that references them.

    Grants and role assignments are deleted; attribution pointers are nulled so
    the audit log and change history survive the account.

    Does not commit — the caller owns the transaction, so the cleanup and the
    delete it precedes land together or not at all.
    """
    for model in _GRANT_TABLES:
        await db.execute(delete(model).where(model.user_id == user_id))
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))

    for model, column in _USER_ATTRIBUTION:
        await db.execute(update(model).where(column == user_id).values({column: None}))


async def remove_role_grants(db: AsyncSession, role_id: int) -> None:
    """Detach a role from every row that references it.

    Does not commit — see `remove_user_grants`.
    """
    for model in _GRANT_TABLES:
        await db.execute(delete(model).where(model.role_id == role_id))
    await db.execute(delete(UserRole).where(UserRole.role_id == role_id))

    # An invitation naming a deleted role should still be redeemable; it just
    # grants nothing until an admin assigns a role after acceptance.
    await db.execute(
        update(UserInvite).where(UserInvite.role_id == role_id).values(role_id=None)
    )
