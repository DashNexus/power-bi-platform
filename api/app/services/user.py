"""User and role management.

Role reads and writes resolve permissions in one grouped query rather than one per
role or per key — the roles admin page loads every role's permissions at once.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Permission, Role, RolePermission, User, UserInvite, UserRole
from app.schemas.common import PaginatedResponse
from app.schemas.user import (
    InviteRequest,
    RoleCreateRequest,
    RoleResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services import principal_cleanup
from app.services.crypto import hash_password

logger = structlog.get_logger(__name__)


async def _user_to_response(db: AsyncSession, user: User) -> UserResponse:
    """Build a UserResponse from a User ORM instance, fetching role names.

    Args:
        db: Active async database session.
        user: The User ORM instance.

    Returns:
        Populated UserResponse.
    """
    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    role_names = [row[0] for row in result.all()]
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        department=user.department,
        phone_number=user.phone_number,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=role_names,
    )


async def get_users(
    db: AsyncSession,
    org_id: int,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResponse[UserResponse]:
    """Return a paginated list of users in the organisation.

    Args:
        db: Active async database session.
        org_id: Filter users by this organisation.
        page: 1-indexed page number.
        page_size: Number of results per page.

    Returns:
        Paginated UserResponse list.
    """
    offset = (page - 1) * page_size
    count_result = await db.execute(
        select(func.count()).select_from(User).where(User.org_id == org_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        # ORDER BY is required, not cosmetic: SQL Server rejects OFFSET without
        # one, and page 2 would otherwise be unrelated to page 1 on any engine.
        select(User)
        .where(User.org_id == org_id)
        .order_by(User.id)
        .offset(offset)
        .limit(page_size)
    )
    users = result.scalars().all()
    items = [await _user_to_response(db, u) for u in users]
    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


async def get_user(db: AsyncSession, user_id: int, org_id: int) -> UserResponse:
    """Fetch a single user by ID, scoped to the organisation.

    Args:
        db: Active async database session.
        user_id: The user's primary key.
        org_id: Organisation scope guard.

    Returns:
        UserResponse for the found user.

    Raises:
        HTTPException: 404 if the user does not exist in the organisation.
    """
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return await _user_to_response(db, user)


async def create_user(
    db: AsyncSession, org_id: int, data: UserCreateRequest
) -> UserResponse:
    """Create a new user in the organisation.

    Args:
        db: Active async database session.
        org_id: The organisation to create the user in.
        data: User creation payload.

    Returns:
        UserResponse for the newly created user.

    Raises:
        HTTPException: 409 if the email is already registered.
    """
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email address is already registered")

    hashed = hash_password(data.password) if data.password else None
    user = User(
        org_id=org_id,
        email=data.email,
        hashed_password=hashed,
        display_name=data.display_name,
        first_name=data.first_name,
        last_name=data.last_name,
        job_title=data.job_title,
        department=data.department,
        timezone=data.timezone,
        phone_number=data.phone_number,
    )
    db.add(user)
    await db.flush()

    for role_id in data.role_ids:
        db.add(UserRole(user_id=user.id, role_id=role_id))

    await db.commit()
    await db.refresh(user)
    logger.info("user.created", user_id=user.id, org_id=org_id)
    return await _user_to_response(db, user)


async def update_user(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    data: UserUpdateRequest,
) -> UserResponse:
    """Update mutable fields on an existing user.

    Args:
        db: Active async database session.
        user_id: The user's primary key.
        org_id: Organisation scope guard.
        data: Fields to update (None values are skipped).

    Returns:
        Updated UserResponse.

    Raises:
        HTTPException: 404 if the user does not exist.
    """
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if data.display_name is not None:
        user.display_name = data.display_name
    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.job_title is not None:
        user.job_title = data.job_title
    if data.department is not None:
        user.department = data.department
    if data.timezone is not None:
        user.timezone = data.timezone
    if data.phone_number is not None:
        user.phone_number = data.phone_number
    if data.is_active is not None:
        user.is_active = data.is_active

    await db.commit()
    await db.refresh(user)
    return await _user_to_response(db, user)


async def deactivate_user(db: AsyncSession, user_id: int, org_id: int) -> None:
    """Soft-delete a user by setting is_active=False.

    Args:
        db: Active async database session.
        user_id: The user's primary key.
        org_id: Organisation scope guard.

    Raises:
        HTTPException: 404 if the user does not exist.
    """
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    logger.info("user.deactivated", user_id=user_id, org_id=org_id)


async def assign_roles(
    db: AsyncSession, user_id: int, org_id: int, role_ids: list[int]
) -> None:
    """Replace all role assignments for a user with the given role IDs.

    Args:
        db: Active async database session.
        user_id: The user's primary key.
        org_id: Organisation scope guard (validates the user exists).
        role_ids: Complete new set of role IDs to assign.

    Raises:
        HTTPException: 404 if the user does not exist.
    """
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    for ur in existing.scalars().all():
        await db.delete(ur)

    for role_id in role_ids:
        db.add(UserRole(user_id=user_id, role_id=role_id))

    await db.commit()


async def get_roles(db: AsyncSession, org_id: int) -> list[RoleResponse]:
    """Return all roles defined for the organisation.

    Args:
        db: Active async database session.
        org_id: Organisation to scope the query to.

    Returns:
        List of RoleResponse objects including permission keys.
    """
    result = await db.execute(select(Role).where(Role.org_id == org_id))
    roles = list(result.scalars().all())
    if not roles:
        return []

    # One grouped query rather than one per role: the roles admin page reads every
    # role's permissions at once, and orgs routinely have a dozen custom roles.
    keys_by_role = await _permission_keys_by_role(db, [r.id for r in roles])
    return [
        RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(keys_by_role.get(role.id, [])),
        )
        for role in roles
    ]


async def _permission_keys_by_role(
    db: AsyncSession, role_ids: list[int]
) -> dict[int, list[str]]:
    """Return {role id: permission keys} for many roles in one query."""
    if not role_ids:
        return {}
    result = await db.execute(
        select(RolePermission.role_id, Permission.key)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id.in_(role_ids))
    )
    keys: dict[int, list[str]] = {}
    for role_id, key in result.all():
        keys.setdefault(role_id, []).append(key)
    return keys


async def _permission_ids_for_keys(db: AsyncSession, keys: list[str]) -> list[int]:
    """Resolve permission keys to ids in one query, silently dropping unknown keys.

    Unknown keys are ignored rather than rejected to match the previous behaviour;
    the roles UI only ever submits keys it was given.
    """
    if not keys:
        return []
    result = await db.execute(select(Permission.id).where(Permission.key.in_(keys)))
    return [row[0] for row in result.all()]


async def create_role(
    db: AsyncSession, org_id: int, data: RoleCreateRequest
) -> RoleResponse:
    """Create a new role and assign permissions to it.

    Args:
        db: Active async database session.
        org_id: Organisation to create the role in.
        data: Role creation payload.

    Returns:
        RoleResponse for the newly created role.
    """
    role = Role(org_id=org_id, name=data.name, description=data.description)
    db.add(role)
    await db.flush()

    for permission_id in await _permission_ids_for_keys(db, data.permission_keys):
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))

    await db.commit()
    await db.refresh(role)
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=data.permission_keys,
    )


async def update_role(
    db: AsyncSession, role_id: int, org_id: int, data: RoleCreateRequest
) -> RoleResponse:
    """Update a role's name, description, and permission set.

    Args:
        db: Active async database session.
        role_id: The role's primary key.
        org_id: Organisation scope guard.
        data: New role data.

    Returns:
        Updated RoleResponse.

    Raises:
        HTTPException: 404 if the role does not exist or is not in the org.
        HTTPException: 403 if attempting to modify a system role.
    """
    result = await db.execute(
        select(Role).where(Role.id == role_id, Role.org_id == org_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be modified")

    role.name = data.name
    role.description = data.description

    # One DELETE rather than a load-then-delete-each round trip per grant.
    await db.execute(sa_delete(RolePermission).where(RolePermission.role_id == role_id))

    for permission_id in await _permission_ids_for_keys(db, data.permission_keys):
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))

    await db.commit()
    await db.refresh(role)
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=data.permission_keys,
    )


async def delete_role(db: AsyncSession, role_id: int, org_id: int) -> None:
    """Delete a role from the organisation.

    Args:
        db: Active async database session.
        role_id: The role's primary key.
        org_id: Organisation scope guard.

    Raises:
        HTTPException: 404 if the role does not exist.
        HTTPException: 403 if the role is a system role.
    """
    result = await db.execute(
        select(Role).where(Role.id == role_id, Role.org_id == org_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be deleted")
    # Grant tables no longer cascade from `roles` — see services/principal_cleanup.py.
    await principal_cleanup.remove_role_grants(db, role_id)
    await db.delete(role)
    await db.commit()
    logger.info("role.deleted", role_id=role_id, org_id=org_id)


async def create_invite(
    db: AsyncSession,
    org_id: int,
    created_by_user_id: int,
    data: InviteRequest,
) -> UserInvite:
    """Create a pending invitation for a new user.

    Args:
        db: Active async database session.
        org_id: Organisation the invite belongs to.
        created_by_user_id: ID of the admin user creating the invite.
        data: Invite payload with target email and optional role.

    Returns:
        The created UserInvite ORM instance.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    invite = UserInvite(
        org_id=org_id,
        email=data.email,
        token=token,
        role_id=data.role_id,
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
        created_at=datetime.now(UTC),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    logger.info("invite.created", email=data.email, org_id=org_id)
    return invite


async def accept_invite(
    db: AsyncSession,
    token: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Accept a pending invitation and create the user account.

    Args:
        db: Active async database session.
        token: The unique invite token from the invitation email.
        password: Plaintext password chosen by the new user.
        display_name: Optional display name for the new user.

    Returns:
        The newly created User ORM instance.

    Raises:
        HTTPException: 404 if the token is invalid or expired.
        HTTPException: 409 if the email is already registered.
    """
    result = await db.execute(select(UserInvite).where(UserInvite.token == token))
    invite = result.scalar_one_or_none()
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    if invite.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invitation has expired")

    existing = await db.execute(select(User).where(User.email == invite.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email address is already registered")

    user = User(
        org_id=invite.org_id,
        email=invite.email,
        hashed_password=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    await db.flush()

    if invite.role_id:
        db.add(UserRole(user_id=user.id, role_id=invite.role_id))

    invite.accepted_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    logger.info("invite.accepted", user_id=user.id, org_id=invite.org_id)
    return user
