"""Token issuance, TOTP enrolment and challenge, and the OAuth exchange."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.auth import LoginRequest, MeResponse, RefreshRequest, TokenResponse
from app.services.crypto import (
    decrypt,
    encrypt,
    generate_totp_secret,
    get_totp_uri,
    verify_password,
    verify_totp,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


def _create_access_token(user: User, role: str) -> str:
    """Encode a short-lived JWT access token for the given user.

    Args:
        user: The authenticated User ORM instance.
        role: The user's highest-privilege role name.

    Returns:
        Signed JWT string.
    """
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": str(user.id),
        "org_id": user.org_id,
        "role": role,
        "email": user.email,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)


def _create_refresh_token(user_id: int) -> str:
    """Encode a long-lived JWT refresh token.

    Args:
        user_id: The user's primary key.

    Returns:
        Signed JWT string.
    """
    expire = datetime.now(UTC) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)


async def _get_user_primary_role(db: AsyncSession, user: User) -> str:
    """Return the name of the user's highest-privilege role.

    Falls back to 'viewer' when the user has no assigned roles.

    Args:
        db: Active async database session.
        user: The User ORM instance.

    Returns:
        Role name string.
    """
    from app.middleware.auth import ROLE_HIERARCHY  # noqa: PLC0415
    from app.models.user import Role, UserRole  # noqa: PLC0415

    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    names = [row[0] for row in result.all()]
    if not names:
        return "viewer"
    return max(names, key=lambda n: ROLE_HIERARCHY.get(n, 0))


@router.post("/token", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_app_db),
) -> TokenResponse:
    """Authenticate with email and password, returning a JWT token pair.

    Validates credentials, checks MFA if enabled, and issues an access/refresh
    token pair on success.
    """
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user is None or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if user.totp_enabled:
        if not data.totp_code:
            raise HTTPException(
                status_code=401,
                detail="TOTP code required — this account has two-factor authentication enabled",
            )
        decrypted_secret = decrypt(user.totp_secret_encrypted)  # type: ignore[arg-type]
        if not verify_totp(decrypted_secret, data.totp_code):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")

    role = await _get_user_primary_role(db, user)
    access_token = _create_access_token(user, role)
    refresh_token = _create_refresh_token(user.id)

    # Update last login timestamp
    from sqlalchemy import update as sa_update  # noqa: PLC0415
    await db.execute(
        sa_update(User)
        .where(User.id == user.id)
        .values(last_login_at=datetime.now(UTC))
    )
    await db.commit()

    # Check if the org requires TOTP and this user hasn't set it up yet
    mfa_setup_required = False
    if not user.totp_enabled:
        from app.models.auth_config import MfaSettings  # noqa: PLC0415

        mfa_result = await db.execute(
            select(MfaSettings).where(MfaSettings.org_id == user.org_id)
        )
        mfa_settings = mfa_result.scalar_one_or_none()
        if mfa_settings and mfa_settings.totp_required:
            mfa_setup_required = True

    audit = AuditLog(
        org_id=user.org_id,
        user_id=user.id,
        action="user.login",
    )
    db.add(audit)
    await db.commit()

    logger.info("auth.login", user_id=user.id, org_id=user.org_id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user_id=user.id,
        org_id=user.org_id,
        role=role,
        email=user.email,
        name=user.display_name,
        avatar_url=user.avatar_url,
        mfa_setup_required=mfa_setup_required,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_app_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access token."""
    from jose import JWTError  # noqa: PLC0415

    try:
        payload = jwt.decode(
            data.refresh_token,
            settings.nextauth_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    role = await _get_user_primary_role(db, user)
    access_token = _create_access_token(user, role)
    new_refresh = _create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> MeResponse:
    """Return the authenticated user's profile summary."""
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return MeResponse(
        user_id=user.id,
        org_id=user.org_id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=current_user.role,
        totp_enabled=user.totp_enabled,
    )


@router.get("/totp/status")
async def totp_status(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, bool]:
    """Return whether TOTP two-factor authentication is enabled for the current user."""
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"enabled": bool(user.totp_enabled)}


@router.post("/totp/setup")
async def totp_setup(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Generate a new TOTP secret, returning the provisioning URI and QR code.

    The QR code is a base64-encoded PNG the client can embed directly in an
    <img> tag. TOTP is not enabled until the user verifies via /totp/enable.
    """
    import base64  # noqa: PLC0415
    import io  # noqa: PLC0415

    import qrcode  # type: ignore[import]  # noqa: PLC0415

    secret = generate_totp_secret()
    encrypted_secret = encrypt(secret)

    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.totp_secret_encrypted = encrypted_secret
    await db.commit()

    uri = get_totp_uri(secret=secret, email=current_user.email)

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return {"provisioning_uri": uri, "qr_code_base64": qr_base64}


@router.post("/totp/enable")
async def totp_enable(
    data: dict[str, str],
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Enable TOTP by verifying a code scanned from the QR code.

    Must be called after /totp/setup. TOTP becomes active only after this
    succeeds — subsequent logins will require a code.
    """
    code = data.get("code", "")

    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.totp_secret_encrypted:
        raise HTTPException(
            status_code=400, detail="TOTP not set up — call /auth/totp/setup first"
        )

    decrypted_secret = decrypt(user.totp_secret_encrypted)
    if not verify_totp(decrypted_secret, code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.totp_enabled = True
    await db.commit()
    logger.info("auth.totp_enabled", user_id=user.id)
    return {"message": "Two-factor authentication enabled successfully"}


@router.post("/totp/disable")
async def totp_disable(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Disable TOTP and clear the stored secret for the current user."""
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    await db.commit()
    logger.info("auth.totp_disabled", user_id=user.id)
    return {"message": "Two-factor authentication disabled"}


@router.post("/totp/verify")
async def totp_verify(
    code: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Verify a TOTP code and activate two-factor authentication for the user.

    Args:
        code: The 6-digit TOTP code from the authenticator app.
    """
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.totp_secret_encrypted:
        raise HTTPException(
            status_code=400, detail="TOTP not set up — call /auth/totp/setup first"
        )

    decrypted_secret = decrypt(user.totp_secret_encrypted)
    if not verify_totp(decrypted_secret, code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.totp_enabled = True
    await db.commit()
    logger.info("auth.totp_enabled", user_id=user.id)
    return {"message": "Two-factor authentication enabled successfully"}


def _create_reset_token(user: User) -> str:
    """Encode a short-lived JWT password-reset token.

    The fingerprint of the current hashed password is embedded so the token is
    single-use — once the password is changed the fingerprint no longer matches.
    """
    expire = datetime.now(UTC) + timedelta(hours=1)
    payload = {
        "sub": str(user.id),
        "purpose": "password_reset",
        "exp": expire,
        # First 8 chars of the current hash — invalidated when password changes
        "fp": (user.hashed_password or "")[:8],
    }
    return jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)


@router.post("/forgot-password")
async def forgot_password(
    data: dict[str, str],
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Request a password reset link for the given email address.

    Always returns the same message regardless of whether the email exists to
    prevent user enumeration. In production the token would be emailed; here it
    is logged at INFO level so developers can test the full flow.
    """
    email = data.get("email", "").strip().lower()
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    if user and user.hashed_password:
        token = _create_reset_token(user)
        import os  # noqa: PLC0415
        app_url = os.getenv("NEXTAUTH_URL", "http://localhost:3000")
        reset_url = f"{app_url}/reset-password?token={token}"
        logger.info(
            "auth.password_reset_requested",
            user_id=user.id,
            reset_url=reset_url,
        )
        # TODO: send via email when notification service is configured

    return {
        "message": (
            "If that email address is registered, a password reset link has been sent. "
            "Check your email — the link expires in 1 hour."
        )
    }


@router.post("/reset-password")
async def reset_password(
    data: dict[str, str],
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str]:
    """Apply a new password using a valid reset token.

    The token is single-use: once the password is changed the embedded
    fingerprint no longer matches, preventing replay attacks.
    """
    from jose import JWTError  # noqa: PLC0415

    from app.services.crypto import hash_password  # noqa: PLC0415

    token = data.get("token", "")
    new_password = data.get("new_password", "")

    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    try:
        payload = jwt.decode(token, settings.nextauth_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link") from exc

    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset link")

    user_id = int(payload["sub"])
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    # Verify fingerprint — ensures the token cannot be reused after password change
    if (user.hashed_password or "")[:8] != payload.get("fp", ""):
        raise HTTPException(status_code=400, detail="This reset link has already been used")

    user.hashed_password = hash_password(new_password)
    await db.commit()

    logger.info("auth.password_reset_complete", user_id=user.id)
    return {"message": "Your password has been reset. You can now sign in with your new password."}


@router.post("/oauth-exchange", response_model=TokenResponse)
async def oauth_exchange(
    data: dict[str, Any],
    db: AsyncSession = Depends(get_app_db),
) -> TokenResponse:
    """Exchange an OAuth provider token for a platform JWT.

    Called by Auth.js after a successful OAuth sign-in to provision a local
    user account (if first login) and return a platform JWT pair.

    Args:
        data: Dict containing provider, access_token, and optionally id_token.
    """
    provider: str = data.get("provider", "")
    access_token: str = data.get("access_token", "")
    id_token: str | None = data.get("id_token")

    if not provider or not access_token:
        raise HTTPException(status_code=400, detail="provider and access_token are required")

    email = await _resolve_oauth_email(provider, access_token, id_token)
    if not email:
        raise HTTPException(
            status_code=400,
            detail=f"Could not retrieve email from {provider} OAuth token",
        )

    # Look up or provision the user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Provision on first OAuth login — no password is set for OAuth users
        user = User(
            email=email,
            is_active=True,
            org_id=1,  # Default org — adjust per multi-tenant provisioning logic
        )
        db.add(user)
        await db.flush()
        logger.info("auth.oauth_provision", email=email, provider=provider)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    role = await _get_user_primary_role(db, user)
    platform_access_token = _create_access_token(user, role)
    refresh_token = _create_refresh_token(user.id)

    from sqlalchemy import update as sa_update  # noqa: PLC0415
    await db.execute(
        sa_update(User)
        .where(User.id == user.id)
        .values(last_login_at=datetime.now(UTC))
    )
    await db.commit()

    logger.info("auth.oauth_exchange", user_id=user.id, provider=provider)
    return TokenResponse(
        access_token=platform_access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


async def _resolve_oauth_email(
    provider: str,
    access_token: str,
    id_token: str | None,
) -> str | None:
    """Call the provider's userinfo endpoint and extract the user's email.

    Args:
        provider: OAuth provider name: 'microsoft', 'google', or 'github'.
        access_token: OAuth access token issued by the provider.
        id_token: OIDC ID token (used as a fallback for some providers).

    Returns:
        Email address string, or None if it could not be determined.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        if provider == "microsoft":
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("mail") or body.get("userPrincipalName")

        elif provider == "google":
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json().get("email")

        elif provider == "github":
            resp = await client.get(
                "https://api.github.com/user",
                headers={**headers, "Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 200:
                email = resp.json().get("email")
                if email:
                    return email

            # Primary email may be private — fetch the verified primary from /user/emails
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={**headers, "Accept": "application/vnd.github+json"},
            )
            if emails_resp.status_code == 200:
                for entry in emails_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        return entry.get("email")

    return None
