"""Custom HTML page management and rendering endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import ROLE_HIERARCHY, CurrentUser, get_current_user, require_role
from app.models.audit import AuditLog
from app.models.page import CustomPage, CustomPagePermission, CustomPageVersion
from app.models.user import UserRole
from app.services import change_ledger as ledger

logger = structlog.get_logger(__name__)

router = APIRouter()

_admin_dep = require_role("admin", "superadmin")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PageCreateRequest(BaseModel):
    """Payload for creating a new custom HTML page."""

    title: str
    slug: str
    content: str
    required_role: str = "viewer"
    is_published: bool = True
    is_home_page: bool = False
    tags: list[str] = []


class PageUpdateRequest(BaseModel):
    """Payload for updating an existing custom HTML page.

    All fields are optional — only supplied fields are changed.
    """

    title: str | None = None
    content: str | None = None
    required_role: str | None = None
    is_published: bool | None = None
    is_home_page: bool | None = None
    tags: list[str] | None = None


class PageResponse(BaseModel):
    """Serialised custom page returned to the client."""

    id: int
    title: str
    slug: str
    content: str
    required_role: str
    is_published: bool
    is_home_page: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: object) -> list[str]:
        return v if isinstance(v, list) else []

    model_config = {"from_attributes": True}


class PageVersionResponse(BaseModel):
    """Serialised custom page version snapshot."""

    id: int
    page_id: int
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_role_access(user_role: str, required_role: str) -> bool:
    """Return True when the user's role level meets or exceeds required_role."""
    user_level = ROLE_HIERARCHY.get(user_role, -1)
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    return user_level >= required_level


def _is_admin(user_role: str) -> bool:
    """Return True when the role is admin or above in the hierarchy."""
    return ROLE_HIERARCHY.get(user_role, -1) >= ROLE_HIERARCHY.get("admin", 2)


async def _filter_accessible_pages(
    db: AsyncSession,
    current_user: CurrentUser,
    pages: Sequence[CustomPage],
) -> list[CustomPage]:
    """Return the pages a non-admin user may access.

    A page with no permission grants is open, subject to its required_role. A
    page with any grant is restricted to the granted users and roles; grants
    take precedence over required_role so custom roles (absent from the role
    hierarchy) can be given access explicitly. Callers handle admin bypass and
    org-home exceptions before calling this.
    """
    if not pages:
        return []

    page_ids = [p.id for p in pages]

    role_result = await db.execute(
        select(UserRole.role_id).where(UserRole.user_id == current_user.user_id)
    )
    role_ids: list[int] = [row[0] for row in role_result.all()]

    # Pages that carry at least one grant row are "restricted".
    restricted_result = await db.execute(
        select(CustomPagePermission.page_id).where(
            CustomPagePermission.page_id.in_(page_ids)
        )
    )
    restricted_ids: set[int] = {row[0] for row in restricted_result.all()}

    # Restricted pages the user is explicitly granted (by user or role).
    grant_conditions: list[Any] = [CustomPagePermission.user_id == current_user.user_id]
    if role_ids:
        grant_conditions.append(CustomPagePermission.role_id.in_(role_ids))
    granted_result = await db.execute(
        select(CustomPagePermission.page_id).where(
            CustomPagePermission.page_id.in_(page_ids),
            or_(*grant_conditions),
        )
    )
    granted_ids: set[int] = {row[0] for row in granted_result.all()}

    accessible: list[CustomPage] = []
    for page in pages:
        if page.id in restricted_ids:
            if page.id in granted_ids:
                accessible.append(page)
        elif _check_role_access(current_user.role, page.required_role):
            accessible.append(page)
    return accessible


async def _page_is_accessible(
    db: AsyncSession,
    current_user: CurrentUser,
    page: CustomPage,
) -> bool:
    """Return True when the current user may view a single page."""
    if _is_admin(current_user.role):
        return True
    return bool(await _filter_accessible_pages(db, current_user, [page]))


async def _get_page_or_404(
    db: AsyncSession,
    page_id: int,
    org_id: int,
) -> CustomPage:
    """Fetch a page by ID within an org, raising 404 if absent."""
    result = await db.execute(
        select(CustomPage).where(
            CustomPage.id == page_id,
            CustomPage.org_id == org_id,
        )
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


async def _create_version_snapshot(
    db: AsyncSession,
    page: CustomPage,
    user_id: int,
) -> None:
    """Insert a version snapshot of the page's current content."""
    version = CustomPageVersion(
        page_id=page.id,
        content=page.content,
        created_by_user_id=user_id,
    )
    db.add(version)


# ---------------------------------------------------------------------------
# Public routes (any authenticated user, filtered by role)
# ---------------------------------------------------------------------------


@router.get("/pages", response_model=list[PageResponse])
async def list_accessible_pages(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[PageResponse]:
    """Return all published pages the current user can access.

    Admins see every published page. Other users see a page when it has no
    permission grants (open, subject to its required_role) or when they have an
    explicit user or role grant for it.
    """
    result = await db.execute(
        select(CustomPage).where(
            CustomPage.org_id == current_user.org_id,
            CustomPage.is_published == True,  # noqa: E712
        )
    )
    pages = result.scalars().all()

    if _is_admin(current_user.role):
        accessible: Sequence[CustomPage] = pages
    else:
        accessible = await _filter_accessible_pages(db, current_user, pages)
    return [PageResponse.model_validate(p) for p in accessible]


@router.get("/pages/home", response_model=PageResponse)
async def get_home_page_inline(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Return the organisation's designated home page, if one is set.

    No role filtering applied — the admin explicitly designated this page as
    the home for all users, so it is accessible regardless of required_role.
    Returns 404 only when no home page has been configured.
    Declared before /pages/{slug} so 'home' is not treated as a slug value.
    """
    result = await db.execute(
        select(CustomPage).where(
            CustomPage.org_id == current_user.org_id,
            CustomPage.is_home_page == True,  # noqa: E712
            CustomPage.is_published == True,  # noqa: E712
        )
    )
    page = result.scalar_one_or_none()

    if page is None:
        raise HTTPException(status_code=404, detail="No home page configured")

    return PageResponse.model_validate(page)


@router.get("/pages/{slug}", response_model=PageResponse)
async def get_page_by_slug(
    slug: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Return a single published page by its URL slug.

    Raises 404 when the page does not exist, is unpublished, or the user's
    role is below the page's required_role. Logs the access to audit_logs.

    Args:
        slug: URL-safe identifier for the page (unique within the org).
    """
    result = await db.execute(
        select(CustomPage).where(
            CustomPage.org_id == current_user.org_id,
            CustomPage.slug == slug,
            CustomPage.is_published == True,  # noqa: E712
        )
    )
    page = result.scalar_one_or_none()

    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    # A page flagged is_home_page is the org entry point, so it is readable by
    # every authenticated user regardless of required_role.
    if not page.is_home_page and not await _page_is_accessible(db, current_user, page):
        # Return 404 rather than 403 to avoid leaking the existence of the page
        raise HTTPException(status_code=404, detail="Page not found")

    # Log page access to the audit trail
    audit = AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="page.view",
        resource_type="custom_page",
        resource_id=page.id,
        resource_name=page.slug,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(audit)
    await db.commit()

    logger.info(
        "pages.view",
        page_id=page.id,
        slug=slug,
        user_id=current_user.user_id,
    )
    return PageResponse.model_validate(page)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@router.get("/admin/pages", response_model=list[PageResponse])
async def list_all_pages(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[PageResponse]:
    """Return all pages for the current organisation, published or not."""
    result = await db.execute(
        select(CustomPage).where(CustomPage.org_id == current_user.org_id)
    )
    pages = result.scalars().all()
    return [PageResponse.model_validate(p) for p in pages]


@router.post("/admin/pages", response_model=PageResponse, status_code=201)
async def create_page(
    data: PageCreateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Create a new custom HTML page and save an initial version snapshot.

    Validates that the slug is unique within the organisation before inserting.

    Args:
        data: Page fields including title, slug, HTML content, and access role.
    """
    # Validate slug uniqueness within the org
    existing = await db.execute(
        select(CustomPage).where(
            CustomPage.org_id == current_user.org_id,
            CustomPage.slug == data.slug,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A page with slug '{data.slug}' already exists in this organisation",
        )

    if data.is_home_page:
        # Clear the flag on any existing home page in this org before setting the new one
        existing_home = await db.execute(
            select(CustomPage).where(
                CustomPage.org_id == current_user.org_id,
                CustomPage.is_home_page == True,  # noqa: E712
            )
        )
        for p in existing_home.scalars().all():
            p.is_home_page = False

    page = CustomPage(
        org_id=current_user.org_id,
        title=data.title,
        slug=data.slug,
        content=data.content,
        required_role=data.required_role,
        is_published=data.is_published,
        is_home_page=data.is_home_page,
        tags=data.tags or None,
        created_by_user_id=current_user.user_id,
    )
    db.add(page)
    # Flush to obtain the page ID before creating the version snapshot
    await db.flush()

    await _create_version_snapshot(db, page, current_user.user_id)
    await ledger.log_create(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="custom_page",
        obj=page,
        resource_name=page.title,
    )
    await db.commit()
    await db.refresh(page)

    logger.info("pages.create", page_id=page.id, slug=page.slug, user_id=current_user.user_id)
    return PageResponse.model_validate(page)


@router.get("/admin/pages/{page_id}", response_model=PageResponse)
async def get_page(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Return a single page by database ID.

    Args:
        page_id: Primary key of the page.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)
    return PageResponse.model_validate(page)


@router.put("/admin/pages/{page_id}", response_model=PageResponse)
async def update_page(
    page_id: int,
    data: PageUpdateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Update a custom page and snapshot the previous content as a new version.

    A version snapshot is created from the existing content before any field
    is overwritten, preserving the full revision history.

    Args:
        page_id: Primary key of the page to update.
        data: Partial update — only non-None fields are applied.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)
    before = ledger.serialize_row(page)

    # Snapshot the current content before overwriting
    await _create_version_snapshot(db, page, current_user.user_id)

    if data.title is not None:
        page.title = data.title
    if data.content is not None:
        page.content = data.content
    if data.required_role is not None:
        page.required_role = data.required_role
    if data.is_published is not None:
        page.is_published = data.is_published
    if data.tags is not None:
        page.tags = data.tags or None
    if data.is_home_page is True:
        # Clear flag on any other home page before setting this one
        existing_home = await db.execute(
            select(CustomPage).where(
                CustomPage.org_id == current_user.org_id,
                CustomPage.is_home_page == True,  # noqa: E712
                CustomPage.id != page_id,
            )
        )
        for p in existing_home.scalars().all():
            p.is_home_page = False
        page.is_home_page = True
    elif data.is_home_page is False:
        page.is_home_page = False

    await ledger.log_update(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="custom_page",
        obj=page,
        before=before,
        resource_name=page.title,
    )
    await db.commit()
    await db.refresh(page)

    logger.info("pages.update", page_id=page.id, user_id=current_user.user_id)
    return PageResponse.model_validate(page)


@router.delete("/admin/pages/{page_id}", response_model=PageResponse)
async def delete_page(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Soft-delete a page by setting is_published=False.

    The page record and its version history are preserved in the database.

    Args:
        page_id: Primary key of the page to soft-delete.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)
    before = ledger.serialize_row(page)
    page.is_published = False
    await ledger.log_update(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="custom_page",
        obj=page,
        before=before,
        resource_name=page.title,
    )
    await db.commit()
    await db.refresh(page)

    logger.info(
        "pages.delete",
        page_id=page.id,
        user_id=current_user.user_id,
    )
    return PageResponse.model_validate(page)


@router.get("/admin/pages/{page_id}/versions", response_model=list[PageVersionResponse])
async def list_versions(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[PageVersionResponse]:
    """Return all version snapshots for a page, newest first.

    Args:
        page_id: Primary key of the page whose history is requested.
    """
    # Verify the page belongs to this org
    await _get_page_or_404(db, page_id, current_user.org_id)

    result = await db.execute(
        select(CustomPageVersion)
        .where(CustomPageVersion.page_id == page_id)
        .order_by(CustomPageVersion.created_at.desc())
    )
    versions = result.scalars().all()
    return [PageVersionResponse.model_validate(v) for v in versions]


@router.post(
    "/admin/pages/{page_id}/versions/{version_id}/restore",
    response_model=PageResponse,
)
async def restore_version(
    page_id: int,
    version_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Restore a previous version by copying its content to the live page.

    Snapshots the current content before overwriting so the restore itself is
    included in the version history and can be undone.

    Args:
        page_id: Primary key of the page to restore.
        version_id: Primary key of the version snapshot to restore from.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)

    result = await db.execute(
        select(CustomPageVersion).where(
            CustomPageVersion.id == version_id,
            CustomPageVersion.page_id == page_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot the current content before the restore overwrites it
    await _create_version_snapshot(db, page, current_user.user_id)

    page.content = version.content
    await db.commit()
    await db.refresh(page)

    logger.info(
        "pages.restore",
        page_id=page.id,
        version_id=version_id,
        user_id=current_user.user_id,
    )
    return PageResponse.model_validate(page)


@router.get("/admin/pages/{page_id}/permissions")
async def get_page_permissions(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, list[int]]:
    """Return the current access grants for a custom page."""
    await _get_page_or_404(db, page_id, current_user.org_id)

    perm_result = await db.execute(
        select(CustomPagePermission).where(CustomPagePermission.page_id == page_id)
    )
    perms = perm_result.scalars().all()
    return {
        "user_ids": [p.user_id for p in perms if p.user_id is not None],
        "role_ids": [p.role_id for p in perms if p.role_id is not None],
    }


@router.put("/admin/pages/{page_id}/permissions")
async def set_page_permissions(
    page_id: int,
    data: dict[str, list[int]],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str | int]:
    """Replace the access control list for a custom page.

    Deletes existing grants and replaces them with the supplied user_ids and
    role_ids. Pass empty lists to remove all restrictions, reverting the page
    to required_role-based access.
    """
    await _get_page_or_404(db, page_id, current_user.org_id)

    await db.execute(
        delete(CustomPagePermission).where(CustomPagePermission.page_id == page_id)
    )

    user_ids: list[int] = data.get("user_ids", [])
    role_ids: list[int] = data.get("role_ids", [])
    for uid in user_ids:
        db.add(CustomPagePermission(page_id=page_id, user_id=uid))
    for rid in role_ids:
        db.add(CustomPagePermission(page_id=page_id, role_id=rid))

    await db.commit()
    total = len(user_ids) + len(role_ids)
    logger.info(
        "pages.permissions.updated",
        page_id=page_id,
        org_id=current_user.org_id,
        grants=total,
    )
    return {"message": f"Permissions updated ({total} grants)"}


@router.post("/admin/pages/{page_id}/set-home", response_model=PageResponse)
async def set_home_page(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Designate this page as the organisation's home page.

    Clears the flag on any previously designated home page first so that at
    most one page per organisation carries is_home_page=True at any time.

    Args:
        page_id: Primary key of the page to promote as home.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)

    # Clear any existing home page for the org
    existing_home = await db.execute(
        select(CustomPage).where(
            CustomPage.org_id == current_user.org_id,
            CustomPage.is_home_page == True,  # noqa: E712
            CustomPage.id != page_id,
        )
    )
    for p in existing_home.scalars().all():
        p.is_home_page = False

    page.is_home_page = True
    await db.commit()
    await db.refresh(page)

    logger.info("pages.set_home", page_id=page.id, user_id=current_user.user_id)
    return PageResponse.model_validate(page)


@router.delete("/admin/pages/{page_id}/set-home", response_model=PageResponse)
async def unset_home_page(
    page_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PageResponse:
    """Remove the home page designation from this page.

    Args:
        page_id: Primary key of the page to demote.
    """
    page = await _get_page_or_404(db, page_id, current_user.org_id)
    page.is_home_page = False
    await db.commit()
    await db.refresh(page)

    logger.info("pages.unset_home", page_id=page.id, user_id=current_user.user_id)
    return PageResponse.model_validate(page)


