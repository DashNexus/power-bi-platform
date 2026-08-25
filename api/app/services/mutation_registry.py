"""Registry describing how each first-class resource is named, scoped, and reverted.

One ``MutationResource`` per resource type ties together the ORM model, a
human-readable name, the parent foreign keys used to remap ids during a grouped
delete-revert, and the access guards. The guards *reuse the routers' existing
``_require_view`` / ``_require_edit`` helpers* (imported lazily to avoid import
cycles) so the ledger's history and revert endpoints inherit the exact same
admin-bypass / permission / grant logic humans get — no reimplemented
authorization.

Wiring a resource into `/changes` means registering it here **and** calling
``services/change_ledger.py``'s ``log_create`` / ``log_update`` / ``log_delete``
from its mutation handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.auth import CurrentUser
from app.models.base import Base

# A guard raises HTTPException (404/403) when access is denied; snapshot is the
# best-available serialized row (after- or before-image) so connection/parent
# scoped resources can resolve their scope even when the row has been deleted.
Guard = Callable[
    [AsyncSession, CurrentUser, "int | None", "dict[str, Any] | None"], Awaitable[None]
]


@dataclass
class MutationResource:
    """How one resource type is named, scoped, and access-controlled."""

    resource_type: str
    model: type[Base]
    resource_name: Callable[[Any], str]
    require_view: Guard
    require_edit: Guard
    # Plural, human-readable name for filter menus. Defaults to the raw
    # resource_type so a newly registered resource is still listed — badly
    # labelled beats missing, which is how `/admin/changes` ended up offering
    # filters for resources this build does not have.
    label: str | None = None
    # column name -> parent resource_type, for grouped delete-revert FK remap.
    # A resource with parent_fks is a child registered so its parent reverts
    # intact; it is not something a person filters a change feed by.
    parent_fks: dict[str, str] = field(default_factory=dict)
    # Run before the row is deleted when a *create* is reverted. Only needed by
    # a resource whose children hold a NO ACTION foreign key to it, where the
    # delete fails until the link is cleared — the same work the resource's own
    # delete handler already does.
    pre_delete: Callable[[AsyncSession, Any], Awaitable[None]] | None = None
    # Rewrite ids buried in a JSON column after a grouped revert reassigned
    # them. `parent_fks` covers real foreign keys; this covers references a
    # column merely *contains*, such as a nav link's /dashboard/{id} href.
    remap_ids: Callable[[Any, dict[str, dict[int, int]]], None] | None = None


_REGISTRY: dict[str, MutationResource] = {}


def register(resource: MutationResource) -> None:
    """Register a resource descriptor (idempotent by resource_type)."""
    _REGISTRY[resource.resource_type] = resource


def get_resource(resource_type: str) -> MutationResource | None:
    """Return the descriptor for a resource type, or None if unregistered."""
    return _REGISTRY.get(resource_type)


def all_resources() -> list[MutationResource]:
    """Return all registered descriptors."""
    return list(_REGISTRY.values())


def top_level_resources() -> list[tuple[str, str]]:
    """Return (resource_type, label) for each resource a person can filter by.

    Child resources — those carrying parent_fks — are registered so a parent
    reverts complete and are left out: nobody filters a change feed by
    "dashboard filter".
    """
    return sorted(
        (r.resource_type, r.label or r.resource_type.replace("_", " ").capitalize())
        for r in _REGISTRY.values()
        if not r.parent_fks
    )


# ---------------------------------------------------------------------------
# Guard adapters (lazy router imports keep this module free of import cycles)
# ---------------------------------------------------------------------------


async def _resolve_field(
    db: AsyncSession,
    model: type[Base],
    resource_id: int | None,
    snapshot: dict[str, Any] | None,
    field_name: str,
) -> Any:  # noqa: ANN401 — returns an arbitrary scope column value
    """Read a scope field (e.g. warehouse_connection_id) from the snapshot, else the row."""
    if snapshot and field_name in snapshot:
        return snapshot[field_name]
    if resource_id is None:
        return None
    result = await db.execute(select(model).where(model.id == resource_id))  # type: ignore[attr-defined]
    row = result.scalar_one_or_none()
    return getattr(row, field_name, None) if row is not None else None


def _admin_guards() -> tuple[Guard, Guard]:
    """Return identical view/edit guards for admin-owned configuration.

    A ``DashboardPermission`` or ``CustomPagePermission`` grant lets a viewer
    *open* the resource; it says nothing about its configuration, so history and
    revert stay with admins. The guard ignores the resource id: a delete-revert
    runs when the row is already gone, and the ledger entry is org-scoped by the
    caller before this runs.
    """

    async def guard(db, cu, rid, snap) -> None:  # noqa: ANN001, ARG001
        from app.routers import dashboards  # noqa: PLC0415

        dashboards._require_admin_role(cu)

    return guard, guard


def _data_dict_guards(model: type[Base]) -> tuple[Guard, Guard]:
    async def view(db, cu, rid, snap) -> None:  # noqa: ANN001
        from app.routers import data_dict  # noqa: PLC0415

        conn_id = await _resolve_field(db, model, rid, snap, "warehouse_connection_id")
        await data_dict._require_conn_view(db, cu, conn_id)

    async def edit(db, cu, rid, snap) -> None:  # noqa: ANN001
        from app.routers import data_dict  # noqa: PLC0415

        conn_id = await _resolve_field(db, model, rid, snap, "warehouse_connection_id")
        await data_dict._require_conn_edit(db, cu, conn_id)

    return view, edit


async def _detach_report_runs(db: AsyncSession, report: Any) -> None:  # noqa: ANN401 — an ExportSchedule
    """Null out the run history's link to a report about to be deleted."""
    from app.services.export_runner import clear_schedule_links  # noqa: PLC0415

    await clear_schedule_links(db, report.id)


def _report_guards(model: type[Base]) -> tuple[Guard, Guard]:
    """Return view/edit guards matching a report's own visibility rule.

    ``routers/exports.py::_load_report`` scopes every read and write by
    ``user_id`` as well as ``org_id``, with no admin bypass: a report carries
    SQL its author wrote and a delivery destination they chose, and nothing in
    this build shares one. The ledger inherits that rule rather than softening
    it, so an admin browsing `/changes` sees *that* a report changed but reverts
    only their own.

    A missing owner denies rather than allows: it means neither the row nor the
    snapshot could say who owns it.
    """

    async def guard(db, cu, rid, snap) -> None:  # noqa: ANN001
        from fastapi import HTTPException  # noqa: PLC0415

        owner_id = await _resolve_field(db, model, rid, snap, "user_id")
        if owner_id != cu.user_id:
            raise HTTPException(status_code=404, detail="Report not found")

    return guard, guard


def _org_settings_guards() -> tuple[Guard, Guard]:
    """Org settings are admin-owned, so reuse the dashboards role check.

    The only ledger-tracked field is the navigation, which is org-wide by
    definition — there is no per-resource scope to inherit here.
    """

    async def guard(db, cu, rid, snap) -> None:  # noqa: ANN001, ARG001
        from app.routers import dashboards  # noqa: PLC0415

        dashboards._require_admin_role(cu)

    return guard, guard


def _describe_grant(grant: Any) -> str:  # noqa: ANN401 — a share row
    """Name a share by whichever principal it targets."""
    if grant.role_id is not None:
        return f"role {grant.role_id}"
    if grant.user_id is not None:
        return f"user {grant.user_id}"
    return "share"


def _register_defaults() -> None:
    from app.models.dashboard import (  # noqa: PLC0415
        DashboardConfig,
        DashboardFilter,
        DashboardPermission,
    )
    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415
    from app.models.export import ExportSchedule  # noqa: PLC0415
    from app.models.org_settings import OrgSettings  # noqa: PLC0415
    from app.models.page import CustomPage, CustomPagePermission  # noqa: PLC0415

    admin_view, admin_edit = _admin_guards()

    # Filters and shares are registered so a deleted dashboard reverts complete:
    # both are cascade-deleted with it, and parent_fks remaps their dashboard_id
    # onto the primary key the recreated dashboard is assigned.
    register(
        MutationResource(
            "dashboard", DashboardConfig, lambda o: o.name, admin_view, admin_edit,
            label="Dashboards",
        )
    )
    register(
        MutationResource(
            "dashboard_filter", DashboardFilter, lambda o: o.filter_label,
            admin_view, admin_edit, parent_fks={"dashboard_id": "dashboard"},
        )
    )
    register(
        MutationResource(
            "dashboard_permission", DashboardPermission, _describe_grant,
            admin_view, admin_edit, parent_fks={"dashboard_id": "dashboard"},
        )
    )

    # Same treatment for custom pages: deleting one takes its shares with it.
    register(
        MutationResource(
            "custom_page", CustomPage, lambda o: o.title, admin_view, admin_edit,
            label="Custom pages",
        )
    )
    register(
        MutationResource(
            "custom_page_permission", CustomPagePermission, _describe_grant,
            admin_view, admin_edit, parent_fks={"page_id": "custom_page"},
        )
    )

    report_view, report_edit = _report_guards(ExportSchedule)
    register(
        MutationResource(
            "report",
            ExportSchedule,
            lambda o: o.name,
            report_view,
            report_edit,
            label="SQL reports",
            # Every run of a report points back at it with a NO ACTION FK, so
            # undoing a create has to detach the history first — exactly what
            # delete_report does. Without this, reverting the creation of a
            # report that has ever run fails on a foreign key.
            pre_delete=_detach_report_runs,
        )
    )

    # Registered so that when deleting a resource prunes its nav link, reverting
    # the delete restores the link along with the resource. remap_ids repoints
    # the restored href: recreating a deleted row assigns it a fresh id.
    from app.services.nav_config import remap_nav_ids  # noqa: PLC0415

    os_view, os_edit = _org_settings_guards()
    register(
        MutationResource(
            "org_settings",
            OrgSettings,
            lambda o: "Navigation",
            os_view,
            os_edit,
            label="Navigation",
            remap_ids=remap_nav_ids,
        )
    )

    dd_view, dd_edit = _data_dict_guards(DataDictionaryEntry)
    register(
        MutationResource(
            "data_dict_entry",
            DataDictionaryEntry,
            lambda o: f"{o.schema_name}.{o.table_name}.{o.column_name or '(table)'}",
            dd_view,
            dd_edit,
            label="Data dictionary",
        )
    )


_register_defaults()
