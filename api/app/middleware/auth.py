"""Request authentication and the principal it produces.

Resolves a user JWT into a `CurrentUser`. Every route except `/auth/*` and
`/health` requires one.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt

from app.config import settings

logger = structlog.get_logger(__name__)

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "analyst": 1,
    "manager": 2,
    "admin": 3,
    "superadmin": 4,
}


@dataclass
class CurrentUser:
    """The authenticated principal for a request.

    Attributes:
        user_id: Database primary key of the user.
        org_id: Organisation the principal belongs to.
        role: Highest-privilege role name.
        email: User's email address.
    """

    user_id: int
    org_id: int
    role: str
    email: str


def verify_token(token: str) -> CurrentUser:
    """Decode and validate a JWT, returning the embedded user context.

    Args:
        token: Raw JWT string (without the "Bearer " prefix).

    Returns:
        CurrentUser populated from the JWT claims.

    Raises:
        HTTPException: With status 401 if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.nextauth_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        logger.warning("auth.token_invalid", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    role = payload.get("role", "viewer")
    email = payload.get("email", "")

    if user_id is None or org_id is None:
        raise HTTPException(status_code=401, detail="Token missing required claims")

    return CurrentUser(
        user_id=int(user_id),
        org_id=int(org_id),
        role=role,
        email=email,
    )


async def get_current_user(request: Request) -> CurrentUser:
    """FastAPI dependency resolving the request's principal from its bearer token.

    Args:
        request: The incoming HTTP request.

    Returns:
        The authenticated CurrentUser.

    Raises:
        HTTPException: 401 when no usable credential is present.
    """
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing or malformed")
    return verify_token(authorization.removeprefix("Bearer ").strip())


def require_role(*roles: str):  # noqa: ANN201
    """Return a FastAPI dependency that enforces one of the given role levels.

    Respects the role hierarchy: a user with a higher-ranked role satisfies
    requirements for any lower-ranked role. For example, require_role("admin")
    also passes superadmin users.

    Args:
        *roles: Role names that are permitted to access the route.

    Returns:
        An async FastAPI dependency function.
    """
    min_level = min(ROLE_HIERARCHY.get(r, 0) for r in roles)

    async def _dependency(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        user_level = ROLE_HIERARCHY.get(current_user.role, -1)
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{current_user.role}' is not authorised for this resource",
            )
        return current_user

    return _dependency
