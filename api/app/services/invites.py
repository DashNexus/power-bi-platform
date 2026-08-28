"""Invitations: issue a link, mail it, and redeem it for an account.

An invitation dies two ways — a week after it was issued, or the moment it is
accepted — and both are enforced here rather than at the call site, because the
accept path is unauthenticated and is the only thing standing between a stale
link and an account.

The link and the email carry the same token by construction. `create_invite`
returns the invite, `invite_url` renders it, and `send_invite_email` mails that
same rendering, so an admin who copies the link and an invitee who clicks the
one in their inbox land on the same page.
"""

from __future__ import annotations

import html
import secrets
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import Org, Role, User, UserInvite, UserRole
from app.schemas.invite import (
    AcceptInviteRequest,
    InvitePreviewResponse,
    InviteRequest,
    InviteResponse,
    InviteStatus,
)
from app.services.crypto import hash_password

logger = structlog.get_logger(__name__)

# One week, as promised in the email body. Changing it means changing the copy.
INVITE_TTL_DAYS = 7

# Matches the accept form and `POST /users/me/password`; an invitee should not
# be able to set a password they would then be refused for rotating.
MIN_PASSWORD_LENGTH = 12


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime.

    A `DateTime(timezone=True)` column comes back aware from PostgreSQL and from
    Azure SQL, but naive from a session that never round-tripped through the
    database — comparing the two raises TypeError, which would surface as a 500
    on the accept page rather than "this link has expired".
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def invite_url(token: str) -> str:
    """Return the accept-invite link for a token."""
    return f"{settings.nextauth_url.rstrip('/')}/accept-invite?token={token}"


def invite_status(invite: UserInvite, *, now: datetime | None = None) -> InviteStatus:
    """Classify an invitation as accepted, expired, or still open."""
    if invite.accepted_at is not None:
        return "accepted"
    if _as_utc(invite.expires_at) < (now or _now()):
        return "expired"
    return "pending"


def _display_name(first: str | None, last: str | None) -> str | None:
    return " ".join(part for part in (first, last) if part) or None


def to_response(
    invite: UserInvite,
    *,
    role_name: str | None = None,
    email_sent: bool | None = None,
    email_error: str | None = None,
) -> InviteResponse:
    """Render an invitation for the admin console, link included."""
    return InviteResponse(
        id=invite.id,
        email=invite.email,
        first_name=invite.first_name,
        last_name=invite.last_name,
        role_id=invite.role_id,
        role_name=role_name,
        status=invite_status(invite),
        invite_url=invite_url(invite.token),
        expires_at=_as_utc(invite.expires_at),
        accepted_at=_as_utc(invite.accepted_at) if invite.accepted_at else None,
        created_at=_as_utc(invite.created_at),
        email_sent=email_sent,
        email_error=email_error,
    )


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------


async def _reject_if_registered(db: AsyncSession, email: str) -> None:
    """Raise 409 when the address already belongs to an account."""
    existing = await db.execute(select(User.id).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email address is already registered")


async def create_invite(
    db: AsyncSession,
    org_id: int,
    created_by_user_id: int,
    data: InviteRequest,
) -> UserInvite:
    """Issue an invitation, replacing any open one for the same address.

    Superseding rather than stacking is what keeps "copy link" unambiguous: with
    two live tokens for one mailbox, the link an admin copies and the link in the
    invitee's inbox need not be the same one.
    """
    await _reject_if_registered(db, data.email)

    await db.execute(
        sa_delete(UserInvite).where(
            UserInvite.org_id == org_id,
            UserInvite.email == data.email,
            UserInvite.accepted_at.is_(None),
        )
    )

    invite = UserInvite(
        org_id=org_id,
        email=data.email,
        token=secrets.token_urlsafe(32),
        first_name=data.first_name,
        last_name=data.last_name,
        role_id=data.role_id,
        created_by_user_id=created_by_user_id,
        expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
        created_at=_now(),
    )
    db.add(invite)
    await db.flush()
    logger.info("invite.created", invite_id=invite.id, org_id=org_id)
    return invite


async def refresh_invite(db: AsyncSession, invite: UserInvite) -> UserInvite:
    """Issue a fresh token and expiry for an existing invitation.

    Resending mints a new token rather than re-mailing the old one, so a link
    that leaked — forwarded, left in a mailing-list archive — stops working the
    moment the admin resends.
    """
    invite.token = secrets.token_urlsafe(32)
    invite.expires_at = _now() + timedelta(days=INVITE_TTL_DAYS)
    await db.flush()
    logger.info("invite.refreshed", invite_id=invite.id, org_id=invite.org_id)
    return invite


async def load_invite(db: AsyncSession, invite_id: int, org_id: int) -> UserInvite:
    """Return an invitation scoped to the organisation, or 404."""
    result = await db.execute(
        select(UserInvite).where(UserInvite.id == invite_id, UserInvite.org_id == org_id)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return invite


async def list_invites(db: AsyncSession, org_id: int) -> list[InviteResponse]:
    """Return every invitation for the organisation, newest first."""
    result = await db.execute(
        select(UserInvite, Role.name)
        .outerjoin(Role, Role.id == UserInvite.role_id)
        .where(UserInvite.org_id == org_id)
        .order_by(UserInvite.created_at.desc(), UserInvite.id.desc())
    )
    return [to_response(invite, role_name=role_name) for invite, role_name in result.all()]


async def role_name_for(db: AsyncSession, role_id: int | None) -> str | None:
    """Return the name of a role, or None when the invitation names no role."""
    if role_id is None:
        return None
    result = await db.execute(select(Role.name).where(Role.id == role_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


async def _org_name(db: AsyncSession, org_id: int) -> str:
    result = await db.execute(select(Org.name).where(Org.id == org_id))
    return result.scalar_one_or_none() or "the BI platform"


def _render_email(
    *, org_name: str, inviter: str | None, url: str, expires_at: datetime
) -> tuple[str, str, str]:
    """Return (subject, plain text, HTML) for an invitation."""
    expiry = _as_utc(expires_at).strftime("%d %B %Y")
    invited_by = f" by {inviter}" if inviter else ""
    subject = f"You have been invited to {org_name}"

    text = (
        f"You have been invited{invited_by} to join {org_name} on the BI platform.\n\n"
        f"Set up your account here:\n{url}\n\n"
        f"This link expires on {expiry} and can only be used once. "
        "If you were not expecting this invitation you can ignore it."
    )

    # Every interpolated value is escaped: the org name and inviter come from
    # rows an admin typed, and this string is rendered as markup in a mail client.
    safe_url = html.escape(url, quote=True)
    body = html.escape(
        f"You have been invited{invited_by} to join {org_name} on the BI platform."
    )
    html_body = f"""<html><body style="font-family:system-ui,sans-serif;color:#1f2430">
  <p>{body}</p>
  <p><a href="{safe_url}"
        style="display:inline-block;padding:10px 18px;border-radius:6px;
               background:#2563eb;color:#ffffff;text-decoration:none">
    Set up your account</a></p>
  <p style="color:#5b6472;font-size:13px">
    Or paste this link into your browser:<br><a href="{safe_url}">{safe_url}</a>
  </p>
  <p style="color:#5b6472;font-size:13px">
    This link expires on {html.escape(expiry)} and can only be used once.
    If you were not expecting this invitation you can ignore it.
  </p>
</body></html>"""

    return subject, text, html_body


async def send_invite_email(
    db: AsyncSession, invite: UserInvite, *, inviter: str | None = None
) -> tuple[bool, str | None]:
    """Mail the invitation link, returning (sent, error).

    A failed send is reported, never raised: the invitation row and its link are
    already valid, and an admin who can see "not sent" can copy the link instead.
    """
    from app.services import pipeline_notifications as delivery  # noqa: PLC0415

    subject, text, html_body = _render_email(
        org_name=await _org_name(db, invite.org_id),
        inviter=inviter,
        url=invite_url(invite.token),
        expires_at=invite.expires_at,
    )
    sent, error = await delivery._send_email(
        [invite.email], subject, text, html_body=html_body
    )
    if not sent:
        logger.warning("invite.email_failed", invite_id=invite.id, error=error)
    return sent, error


# ---------------------------------------------------------------------------
# Redeeming
# ---------------------------------------------------------------------------


async def _load_by_token(db: AsyncSession, token: str) -> UserInvite:
    result = await db.execute(select(UserInvite).where(UserInvite.token == token))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="This invitation link is not valid.")
    return invite


async def preview_invite(db: AsyncSession, token: str) -> InvitePreviewResponse:
    """Describe an invitation to the unauthenticated accept page."""
    invite = await _load_by_token(db, token)
    return InvitePreviewResponse(
        email=invite.email,
        org_name=await _org_name(db, invite.org_id),
        first_name=invite.first_name,
        last_name=invite.last_name,
        status=invite_status(invite),
        expires_at=_as_utc(invite.expires_at),
    )


async def accept_invite(db: AsyncSession, token: str, data: AcceptInviteRequest) -> User:
    """Redeem an invitation and create the account it was issued for.

    The address comes from the invitation, never from the request: the token
    proves the holder reached the mailbox it was sent to, and letting them name
    a different address would make an invitation to one person an account for
    anyone.
    """
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )

    invite = await _load_by_token(db, token)
    status = invite_status(invite)
    if status == "accepted":
        raise HTTPException(
            status_code=409, detail="This invitation has already been used."
        )
    if status == "expired":
        raise HTTPException(
            status_code=410,
            detail="This invitation has expired. Ask an administrator for a new one.",
        )

    await _reject_if_registered(db, invite.email)

    first_name = data.first_name or invite.first_name
    last_name = data.last_name or invite.last_name
    user = User(
        org_id=invite.org_id,
        email=invite.email,
        hashed_password=hash_password(data.password),
        first_name=first_name,
        last_name=last_name,
        display_name=_display_name(first_name, last_name),
    )
    db.add(user)
    await db.flush()

    if invite.role_id is not None:
        db.add(UserRole(user_id=user.id, role_id=invite.role_id))

    invite.accepted_at = _now()
    await db.commit()
    logger.info("invite.accepted", user_id=user.id, org_id=invite.org_id)
    return user
