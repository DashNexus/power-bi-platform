"""Aggregate the counts, configuration state, and activity the /admin landing page shows.

The page renders two dozen numbers. Fetching them one endpoint at a time would
be two dozen round trips on every visit to /admin, so all of the counts are
built as scalar subqueries and read in a **single** query (see `api/CLAUDE.md` →
*Performance*); five more queries cover the rows that are not counts. The total
is constant in the size of the organisation.

Nothing here decides what deserves attention — the numbers are returned as they
are and the frontend composes the warnings, so a threshold can be re-worded
without a backend release.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.config import FEATURE_ENV_VARS, settings
from app.models.audit import AuditLog
from app.models.auth_config import AuthProviderConfig, MfaSettings
from app.models.base import Base
from app.models.bi_connection import BiConnection
from app.models.change_ledger import ChangeLedgerEntry
from app.models.dashboard import DashboardConfig
from app.models.data_dict import DataDictionaryEntry
from app.models.data_pipeline import DataPipelineConnection
from app.models.export import ExportSchedule
from app.models.feature_flag import FeatureFlag
from app.models.org_settings import OrgSettings
from app.models.page import CustomPage
from app.models.pipeline_notification import NotificationGroup
from app.models.user import Org, Role, User, UserInvite
from app.models.warehouse import WarehouseConnection
from app.sql_compat import is_false, is_true

#: A sign-in inside this window counts the user as recently active.
ACTIVE_WINDOW_DAYS = 7

#: Entries returned per activity feed.
ACTIVITY_LIMIT = 8


def _count(model: type[Base], *conditions: ColumnElement[bool]) -> ScalarSelect[int]:
    """Return a `COUNT(*)` over one table as a scalar subquery."""
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return stmt.scalar_subquery()


def _count_specs(org_id: int, now: datetime) -> dict[str, ScalarSelect[int]]:
    """Build every count the overview needs, keyed by its response field name."""
    recently_active = now - timedelta(days=ACTIVE_WINDOW_DAYS)

    return {
        # People
        "users_total": _count(User, User.org_id == org_id),
        "users_active": _count(User, User.org_id == org_id, is_true(User.is_active)),
        "users_inactive": _count(User, User.org_id == org_id, is_false(User.is_active)),
        "users_with_mfa": _count(
            User, User.org_id == org_id, is_true(User.is_active), is_true(User.totp_enabled)
        ),
        "users_never_signed_in": _count(
            User, User.org_id == org_id, is_true(User.is_active), User.last_login_at.is_(None)
        ),
        "users_active_recently": _count(
            User, User.org_id == org_id, User.last_login_at >= recently_active
        ),
        "roles": _count(Role, Role.org_id == org_id),
        "pending_invites": _count(
            UserInvite,
            UserInvite.org_id == org_id,
            UserInvite.accepted_at.is_(None),
            UserInvite.expires_at > now,
        ),
        "expired_invites": _count(
            UserInvite,
            UserInvite.org_id == org_id,
            UserInvite.accepted_at.is_(None),
            UserInvite.expires_at <= now,
        ),
        # Access
        "sso_providers_total": _count(AuthProviderConfig, AuthProviderConfig.org_id == org_id),
        "sso_providers_enabled": _count(
            AuthProviderConfig,
            AuthProviderConfig.org_id == org_id,
            is_true(AuthProviderConfig.enabled),
        ),
        # Content
        "dashboards": _count(
            DashboardConfig, DashboardConfig.org_id == org_id, is_true(DashboardConfig.is_active)
        ),
        "custom_pages": _count(CustomPage, CustomPage.org_id == org_id),
        # Data platform
        "warehouse_connections": _count(
            WarehouseConnection,
            WarehouseConnection.org_id == org_id,
            is_true(WarehouseConnection.is_active),
        ),
        "bi_connections": _count(
            BiConnection, BiConnection.org_id == org_id, is_true(BiConnection.is_active)
        ),
        "pipeline_connections": _count(
            DataPipelineConnection,
            DataPipelineConnection.org_id == org_id,
            is_true(DataPipelineConnection.is_active),
        ),
        "notification_groups": _count(NotificationGroup, NotificationGroup.org_id == org_id),
        "dictionary_entries": _count(DataDictionaryEntry, DataDictionaryEntry.org_id == org_id),
        "export_schedules": _count(ExportSchedule, ExportSchedule.org_id == org_id),
        # Activity volume
        "audit_events_recent": _count(
            AuditLog, AuditLog.org_id == org_id, AuditLog.created_at >= recently_active
        ),
        "changes_recent": _count(
            ChangeLedgerEntry,
            ChangeLedgerEntry.org_id == org_id,
            ChangeLedgerEntry.created_at >= recently_active,
        ),
    }


async def _load_counts(db: AsyncSession, org_id: int, now: datetime) -> dict[str, int]:
    """Read every count in one round trip."""
    specs = _count_specs(org_id, now)
    row = (await db.execute(select(*(sq.label(name) for name, sq in specs.items())))).one()
    return {name: int(value or 0) for name, value in row._mapping.items()}


async def _load_org(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Return the organisation's identity and branding state."""
    row = (
        await db.execute(
            select(
                Org.name,
                Org.slug,
                Org.created_at,
                OrgSettings.app_name,
                OrgSettings.logo_url,
                OrgSettings.audit_retention_days,
            )
            .outerjoin(OrgSettings, OrgSettings.org_id == Org.id)
            .where(Org.id == org_id)
        )
    ).first()
    if row is None:
        return {"id": org_id, "name": None}

    return {
        "id": org_id,
        "name": row.name,
        "slug": row.slug,
        "created_at": row.created_at,
        "app_name": row.app_name,
        "logo_url": row.logo_url,
        "audit_retention_days": row.audit_retention_days,
    }


async def _load_features(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Summarise feature-flag state, honouring `FEATURE_*` env overrides.

    Mirrors `GET /admin/features`: an env var wins over the stored value, and a
    key with no row at all is off.
    """
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.org_id == org_id))
    stored = {flag.feature_key: flag.enabled for flag in result.scalars().all()}
    overrides = settings.feature_overrides

    keys = sorted(set(FEATURE_ENV_VARS) | set(stored))
    enabled = [key for key in keys if overrides.get(key, stored.get(key, False))]
    return {
        "total": len(keys),
        "enabled": len(enabled),
        "disabled": len(keys) - len(enabled),
        "env_overrides": len(overrides),
        "enabled_keys": enabled,
    }


async def _load_auth(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Return the org's MFA posture."""
    row = (
        await db.execute(select(MfaSettings).where(MfaSettings.org_id == org_id))
    ).scalar_one_or_none()
    return {
        "totp_enabled": row.totp_enabled if row else True,
        "totp_required": row.totp_required if row else False,
        "email_otp_enabled": row.email_otp_enabled if row else False,
        "grace_period_days": row.grace_period_days if row else 0,
    }


async def _load_recent_audit(db: AsyncSession, org_id: int) -> list[dict[str, Any]]:
    """Return the newest audit entries with the acting user resolved."""
    rows = await db.execute(
        select(AuditLog, User.email, User.display_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(ACTIVITY_LIMIT)
    )
    return [
        {
            "id": log.id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_name": log.resource_name,
            "user_name": display_name or email,
            "created_at": log.created_at,
        }
        for log, email, display_name in rows.all()
    ]


async def _load_recent_changes(db: AsyncSession, org_id: int) -> list[dict[str, Any]]:
    """Return the newest change-ledger entries with the actor resolved."""
    rows = await db.execute(
        select(ChangeLedgerEntry, User.email, User.display_name)
        .outerjoin(User, User.id == ChangeLedgerEntry.actor_user_id)
        .where(ChangeLedgerEntry.org_id == org_id)
        .order_by(ChangeLedgerEntry.created_at.desc(), ChangeLedgerEntry.id.desc())
        .limit(ACTIVITY_LIMIT)
    )
    return [
        {
            "id": entry.id,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "resource_name": entry.resource_name,
            "action": entry.action,
            "source": entry.source,
            "actor_name": display_name or email,
            "reverted_at": entry.reverted_at,
            "created_at": entry.created_at,
        }
        for entry, email, display_name in rows.all()
    ]


async def get_overview(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Return everything the admin overview page renders.

    Returns:
        A dict with `org`, `counts`, `features`, `auth`, `recent_audit`,
        `recent_changes`, and the window the counts were computed over, so the
        UI can label them without hardcoding a number.
    """
    now = datetime.now(UTC)

    counts = await _load_counts(db, org_id, now)
    org = await _load_org(db, org_id)
    features = await _load_features(db, org_id)
    auth = await _load_auth(db, org_id)
    recent_audit = await _load_recent_audit(db, org_id)
    recent_changes = await _load_recent_changes(db, org_id)

    return {
        "org": org,
        "counts": counts,
        "features": features,
        "auth": auth,
        "recent_audit": recent_audit,
        "recent_changes": recent_changes,
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "generated_at": now,
    }
