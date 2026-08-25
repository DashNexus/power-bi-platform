"""Request and response models for authentication."""

from __future__ import annotations

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """JWT token pair and user context returned after successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    # User context — consumed by the Next.js credentials authorize() callback
    user_id: int = 0
    org_id: int = 0
    role: str = ""
    email: str = ""
    name: str | None = None
    avatar_url: str | None = None
    # True when the org requires TOTP and this user hasn't set it up yet
    mfa_setup_required: bool = False


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    email: str
    password: str
    totp_code: str | None = None


class RefreshRequest(BaseModel):
    """Refresh token submitted to obtain a new access token."""

    refresh_token: str


class MeResponse(BaseModel):
    """Current authenticated user summary."""

    user_id: int
    org_id: int
    email: str
    display_name: str | None
    avatar_url: str | None = None
    role: str
    totp_enabled: bool
