"""Redeeming an invitation — the two routes that cannot require a session.

Everything about *issuing* an invitation is admin-only and lives in
`routers/admin.py`. These two are reached by someone who has no account yet, so
the token in the URL is the only credential there is: it is unguessable, it
expires after a week, and accepting stamps it used.

They are mounted at `/invites`, not under `/admin`, because an unauthenticated
route beneath an admin prefix reads as an oversight every time it is reviewed.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.schemas.common import MessageResponse
from app.schemas.invite import AcceptInviteRequest, InvitePreviewResponse
from app.services import invites as invite_svc
from app.services.audit import audit_action

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/invites/{token}", response_model=InvitePreviewResponse)
async def preview_invite(
    token: str,
    db: AsyncSession = Depends(get_app_db),
) -> InvitePreviewResponse:
    """Describe the invitation behind a token so the accept page can render it.

    Returns the state rather than refusing it: an invitee holding an expired
    link needs to be told that, not shown an empty form that fails on submit.
    """
    return await invite_svc.preview_invite(db, token)


@router.post("/invites/{token}/accept", response_model=MessageResponse)
async def accept_invite(
    token: str,
    data: AcceptInviteRequest,
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Redeem an invitation and create the account."""
    user = await invite_svc.accept_invite(db, token, data)
    # Committed separately: the account exists either way, and an audit failure
    # must not be what stops someone signing in for the first time.
    await audit_action(
        db,
        org_id=user.org_id,
        user_id=user.id,
        action="invite.accepted",
        resource_type="user",
        resource_id=user.id,
        resource_name=user.email,
    )
    await db.commit()
    return MessageResponse(
        message="Your account is ready. Sign in with your email address and new password."
    )
