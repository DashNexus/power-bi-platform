"""Self-service profile, avatars, and the shared user directory.

Everything here is about the *current* user acting on their own account, plus one
read-only roster that any authenticated user may read. Administering **other**
people stays in `routers/admin.py` behind `require_role("admin")`.

Two gaps this closes:

  * A user could not change their own display name or password. The profile page
    told them to "contact your administrator", and the only password path was the
    emailed reset flow — so a logged-in user with a working password had no way to
    rotate it.
  * Every people-picker needed a roster, and the only one available was the
    admin-only `GET /admin/users`. `TeamPanel` called it anyway and swallowed the
    403, so a non-admin project manager saw an empty "add member" list.
"""

from __future__ import annotations

import io

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.user import Role, User, UserRole
from app.services import avatars
from app.services.crypto import hash_password, verify_password
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

# Long enough to matter, short enough not to fight a password manager.
MIN_PASSWORD_LENGTH = 12


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MyProfileResponse(BaseModel):
    """The current user's own profile, including fields only they can edit."""

    user_id: int
    org_id: int
    email: str
    display_name: str | None
    first_name: str | None
    last_name: str | None
    job_title: str | None
    department: str | None
    phone_number: str | None
    timezone: str | None
    avatar_url: str | None
    role: str
    roles: list[str]
    totp_enabled: bool
    # True when a password is set at all: an SSO-only account has none, and must
    # not be shown a "change password" form it cannot use.
    has_password: bool


class ProfileUpdate(BaseModel):
    """Fields a user may change on their own account.

    Deliberately excludes `is_active`. Those drive AI task
    assignment and billing, so they are the org's to set, not the subject's —
    self-editing a bill rate is the obvious problem.
    """

    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    phone_number: str | None = None
    timezone: str | None = None

    @field_validator(
        "display_name",
        "first_name",
        "last_name",
        "job_title",
        "department",
        "phone_number",
        "timezone",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Treat a cleared form field as "unset" rather than an empty string."""
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value


class PasswordChange(BaseModel):
    """Payload for an authenticated password change."""

    current_password: str
    new_password: str


class DirectoryEntry(BaseModel):
    """Minimal user record for assignee pickers and avatar rendering."""

    user_id: int
    display_name: str | None
    email: str
    job_title: str | None
    avatar_url: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_user(db: AsyncSession, user_id: int) -> User:
    """Return the user row, or 404."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _role_names(db: AsyncSession, user_id: int) -> list[str]:
    """Return the names of the roles assigned to a user."""
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(
            UserRole.user_id == user_id
        )
    )
    return [row[0] for row in result.all()]


async def _profile(db: AsyncSession, user: User, role: str) -> MyProfileResponse:
    """Build the self-profile response for a loaded user."""
    return MyProfileResponse(
        user_id=user.id,
        org_id=user.org_id,
        email=user.email,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        job_title=user.job_title,
        department=user.department,
        phone_number=user.phone_number,
        timezone=user.timezone,
        avatar_url=user.avatar_url,
        role=role,
        roles=await _role_names(db, user.id),
        totp_enabled=user.totp_enabled,
        has_password=bool(user.hashed_password),
    )


# ---------------------------------------------------------------------------
# Own profile
# ---------------------------------------------------------------------------


@router.get("/users/me", response_model=MyProfileResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> MyProfileResponse:
    """Return the current user's full profile."""
    user = await _load_user(db, current_user.user_id)
    return await _profile(db, user, current_user.role)


@router.put("/users/me", response_model=MyProfileResponse)
async def update_my_profile(
    data: ProfileUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> MyProfileResponse:
    """Update the current user's own editable profile fields."""
    user = await _load_user(db, current_user.user_id)

    for field in (
        "display_name",
        "first_name",
        "last_name",
        "job_title",
        "department",
        "phone_number",
        "timezone",
    ):
        # `exclude_unset` keeps an omitted field untouched while still allowing an
        # explicit null to clear one — a plain `is not None` check cannot do both.
        if field in data.model_fields_set:
            setattr(user, field, getattr(data, field))

    await db.commit()
    await db.refresh(user)
    logger.info("user.profile_updated", user_id=user.id, org_id=user.org_id)
    return await _profile(db, user, current_user.role)


@router.post("/users/me/password", status_code=204)
async def change_my_password(
    data: PasswordChange,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Change the current user's password, verifying the existing one first.

    Requiring the current password is what makes this safe to expose on a live
    session: a borrowed unlocked laptop cannot be used to lock the owner out.
    """
    user = await _load_user(db, current_user.user_id)

    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="This account signs in with an identity provider and has no password.",
        )
    if not verify_password(data.current_password, user.hashed_password):
        # Deliberately vague: this is an authenticated route, so the only thing
        # left to protect is whether a guess was close.
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(data.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if data.new_password == data.current_password:
        raise HTTPException(
            status_code=422, detail="New password must differ from the current one."
        )

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    logger.info("user.password_changed", user_id=user.id, org_id=user.org_id)


# ---------------------------------------------------------------------------
# Avatars
# ---------------------------------------------------------------------------


async def _store_avatar(db: AsyncSession, user: User, file: UploadFile) -> str:
    """Validate, store, and attach an avatar image; return its URL."""
    from app.storage import get_filesystem, get_storage_path  # noqa: PLC0415

    try:
        filename = avatars.build_filename(file.content_type or "")
    except avatars.AvatarError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    payload = await file.read(avatars.MAX_AVATAR_BYTES + 1)
    if len(payload) > avatars.MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Image too large — 4 MB maximum.")
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    fs = get_filesystem()
    await fs._pipe_file(
        get_storage_path(avatars.storage_key(user.org_id, user.id, filename)), payload
    )

    user.avatar_url = avatars.avatar_url(user.id, filename)
    await db.commit()
    logger.info("user.avatar_uploaded", user_id=user.id, org_id=user.org_id)
    return user.avatar_url


@router.post("/users/me/avatar")
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Upload the current user's avatar and return its URL."""
    user = await _load_user(db, current_user.user_id)
    return {"avatar_url": await _store_avatar(db, user, file)}


@router.delete("/users/me/avatar", status_code=204)
async def delete_my_avatar(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Remove the current user's avatar, falling back to initials.

    Only the pointer is cleared; the object is left in storage. Avatars are tiny
    and unguessably named, and a failed delete must not leave the row pointing at
    a file that is already gone.
    """
    user = await _load_user(db, current_user.user_id)
    user.avatar_url = None
    await db.commit()
    logger.info("user.avatar_removed", user_id=user.id, org_id=user.org_id)


@router.get("/users/{user_id}/avatar/{filename}")
async def serve_avatar(
    user_id: int,
    filename: str,
    db: AsyncSession = Depends(get_app_db),
) -> StreamingResponse:
    """Serve a stored avatar image.

    Unauthenticated so it renders as a plain `<img>`, exactly like client brand
    assets: access is gated by the unguessable UUID filename, and the owning org
    is resolved from the user id to build the storage key. Only the generated
    filename shape is accepted, so no path can be traversed out of the key.
    """
    from app.storage import get_filesystem, get_storage_path  # noqa: PLC0415

    if not avatars.is_valid_filename(filename):
        raise HTTPException(status_code=404, detail="Avatar not found")

    result = await db.execute(select(User.org_id).where(User.id == user_id))
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(status_code=404, detail="Avatar not found")

    fs = get_filesystem()
    try:
        payload: bytes = await fs._cat_file(
            get_storage_path(avatars.storage_key(org_id, user_id, filename))
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Avatar not found") from exc

    return StreamingResponse(
        io.BytesIO(payload),
        media_type=avatars.content_type_for(filename),
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------


@router.get("/users/directory", response_model=list[DirectoryEntry])
async def list_directory(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[DirectoryEntry]:
    """Return active users in the org for assignee pickers and avatar rendering.

    Available to any authenticated user, because knowing who your colleagues are
    is not privileged — the fields are exactly what a picker renders, and nothing
    more. Contact details, rates, capacity, and status stay on the admin API.

    If a `GET /users/{user_id}` route is ever added it must be declared *after*
    this one and after `/users/me`: FastAPI matches in declaration order and
    would otherwise try to parse "directory" as an int.
    """
    result = await db.execute(
        select(User.id, User.display_name, User.email, User.job_title, User.avatar_url)
        .where(User.org_id == current_user.org_id, is_true(User.is_active))
        .order_by(User.display_name, User.email)
    )
    return [
        DirectoryEntry(
            user_id=uid,
            display_name=display_name,
            email=email,
            job_title=job_title,
            avatar_url=avatar_url,
        )
        for uid, display_name, email, job_title, avatar_url in result.all()
    ]
