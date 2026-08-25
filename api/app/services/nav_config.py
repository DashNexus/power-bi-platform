"""Keep the org's configurable portal navigation free of links to deleted resources.

``OrgSettings.nav_config`` is admin-authored: the shape is validated
(``schemas/nav_config.py``) but nothing ties an href to a live row. Delete the
dashboard behind a nav link and every user in the organisation gets a nav entry
that 404s, with no indication of why.

Resource delete handlers call :func:`prune_nav_links` with the hrefs the deleted
resource owned. When a ``LedgerContext`` is supplied, the settings update joins
the delete's correlation id, so reverting the delete brings the nav entry back
with the resource — and :func:`remap_nav_ids` repoints it, because a recreated
row is assigned a fresh primary key.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_settings import OrgSettings

logger = structlog.get_logger(__name__)

# Which routes a resource of each kind can be linked by. The keys mirror the
# categories the nav-config page offers as suggestions; a kind with no entry
# prunes nothing rather than guessing at a path.
_RESOURCE_ROUTES: dict[str, tuple[str, ...]] = {
    "dashboard": ("/dashboard/{}",),
    "custom_page": ("/pages/{}",),
    # A data dictionary is browsed per warehouse connection, so deleting the
    # connection takes the dictionary link with it.
    "warehouse_connection": ("/data-dicts/{}",),
    "data_pipeline": ("/pipelines/{}",),
}

# The inverse, for following an id that changed during a grouped revert. Only
# resource types the mutation registry can recreate appear here: a route whose
# resource cannot be restored never has a new id to point at.
_ROUTE_RESOURCE: dict[str, str] = {
    "/dashboard": "dashboard",
}


def resource_hrefs(kind: str, identifier: int | str) -> list[str]:
    """Return the nav hrefs a resource of ``kind`` can be linked by."""
    return [template.format(identifier) for template in _RESOURCE_ROUTES.get(kind, ())]


def _normalise(href: Any) -> str:  # noqa: ANN401 — href comes from stored JSON
    """Return an href comparable across trailing-slash and casing differences."""
    if not isinstance(href, str):
        return ""
    return href.strip().rstrip("/").lower() or "/"


def _prune_items(items: list[Any], targets: set[str]) -> tuple[list[Any], list[str]]:
    """Return (kept items, removed hrefs), recursing one level into dropdowns."""
    kept: list[Any] = []
    removed: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue

        if item.get("type") == "dropdown":
            children = item.get("items")
            if isinstance(children, list):
                kept_children, removed_children = _prune_items(children, targets)
                removed.extend(removed_children)
                # A dropdown emptied by the prune is dead weight: it renders as a
                # menu that opens onto nothing.
                if not kept_children:
                    continue
                item = {**item, "items": kept_children}
            kept.append(item)
            continue

        if _normalise(item.get("href")) in targets:
            removed.append(str(item.get("href")))
            continue
        kept.append(item)
    return kept, removed


async def prune_nav_links(
    db: AsyncSession,
    org_id: int,
    hrefs: list[str],
    *,
    ctx: Any = None,  # noqa: ANN401 — change_ledger.LedgerContext, imported lazily
) -> list[str]:
    """Remove nav entries pointing at ``hrefs``, returning the hrefs removed.

    Never raises. A nav entry outliving its resource is a cosmetic problem, and
    failing someone's delete over it would be the worse outcome. The caller owns
    the commit.
    """
    if not hrefs:
        return []
    try:
        settings_row = (
            await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
        ).scalar_one_or_none()
        if settings_row is None or not settings_row.nav_config:
            return []

        targets = {_normalise(href) for href in hrefs} - {""}
        kept, removed = _prune_items(list(settings_row.nav_config), targets)
        if not removed:
            return []

        if ctx is not None:
            from app.services import change_ledger as ledger  # noqa: PLC0415

            before = ledger.serialize_row(settings_row)
            settings_row.nav_config = kept or None
            await ledger.log_update(
                db,
                ctx=ctx,
                resource_type="org_settings",
                obj=settings_row,
                before=before,
                resource_name="Navigation",
            )
        else:
            settings_row.nav_config = kept or None

        logger.info("nav_config.pruned", org_id=org_id, removed=removed)
        return removed
    except Exception as exc:  # noqa: BLE001 — cleanup must never block the delete
        logger.warning("nav_config.prune_failed", org_id=org_id, hrefs=hrefs, error=str(exc))
        return []


def _remap_href(href: Any, id_maps: dict[str, dict[int, int]]) -> Any:  # noqa: ANN401
    """Point an href at a resource's new id, if that id changed."""
    if not isinstance(href, str):
        return href
    prefix, _, tail = href.rstrip("/").rpartition("/")
    resource_type = _ROUTE_RESOURCE.get(prefix)
    if resource_type is None or not tail.isdigit():
        return href
    new_id = id_maps.get(resource_type, {}).get(int(tail))
    return href if new_id is None else f"{prefix}/{new_id}"


def remap_nav_ids(settings_row: Any, id_maps: dict[str, dict[int, int]]) -> None:  # noqa: ANN401
    """Rewrite nav hrefs after a grouped revert reassigned resource ids.

    Recreating a deleted row assigns it a fresh primary key, so a nav link
    restored from a snapshot points at an id the resource no longer has. Called
    by the revert engine once every row in the group is back.
    """
    nav = settings_row.nav_config
    if not nav or not id_maps:
        return

    def walk(items: list[Any]) -> list[Any]:
        out: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                out.append(item)
                continue
            updated = dict(item)
            if "href" in updated:
                updated["href"] = _remap_href(updated["href"], id_maps)
            if isinstance(updated.get("items"), list):
                updated["items"] = walk(updated["items"])
            out.append(updated)
        return out

    remapped = walk(list(nav))
    if remapped != nav:
        settings_row.nav_config = remapped
        logger.info("nav_config.ids_remapped", org_id=settings_row.org_id)
