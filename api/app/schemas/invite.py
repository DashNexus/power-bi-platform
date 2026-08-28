"""Request and response models for user invitations.

An invitation is two things at once: a link the admin can copy and hand over
themselves, and an email the API sends on their behalf. Both carry the same
token, so `InviteResponse` always returns `invite_url` — the copy button has to
work whether or not SMTP is configured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

InviteStatus = Literal["pending", "accepted", "expired"]


def _clean_email(value: str) -> str:
    """Normalise an address so two spellings of one mailbox cannot both be invited."""
    cleaned = value.strip().lower()
    # Not a full RFC check — the account is only usable once the invitee opens
    # the link that was mailed to this address, so the address proves itself.
    if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return cleaned


class InviteRequest(BaseModel):
    """Payload for inviting someone to join the organisation."""

    email: str
    first_name: str | None = None
    last_name: str | None = None
    role_id: int | None = None
    # An admin who intends to paste the link into Teams does not need the email
    # as well, and a deployment without SMTP has no way to send one.
    send_email: bool = True

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _clean_email(value)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class InviteResponse(BaseModel):
    """An invitation as the admin console shows it."""

    id: int
    email: str
    first_name: str | None
    last_name: str | None
    role_id: int | None
    role_name: str | None
    status: InviteStatus
    invite_url: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    # None when no send was attempted (send_email=false, or a plain listing).
    email_sent: bool | None = None
    email_error: str | None = None


class InvitePreviewResponse(BaseModel):
    """What the unauthenticated accept page may know about a token.

    Only what the invitee already has in their inbox: who invited them and to
    what. No role, no inviter identity, nothing about the org's other members.
    """

    email: str
    org_name: str
    first_name: str | None
    last_name: str | None
    status: InviteStatus
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    """Payload the invitee submits to turn their invitation into an account."""

    password: str
    first_name: str | None = None
    last_name: str | None = None

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
