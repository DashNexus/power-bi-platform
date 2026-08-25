"""Request and response models for users, roles, and permissions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UserResponse(BaseModel):
    """Full user record returned by the admin API."""

    id: int
    email: str
    display_name: str | None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    avatar_url: str | None = None
    timezone: str | None = None
    phone_number: str | None = None
    is_active: bool
    totp_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str]

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    """Payload for creating a new user directly (not via invitation)."""

    email: str
    password: str | None = None
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    timezone: str | None = None
    phone_number: str | None = None
    role_ids: list[int] = []


class UserUpdateRequest(BaseModel):
    """Payload for updating mutable user fields."""

    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    timezone: str | None = None
    phone_number: str | None = None
    is_active: bool | None = None


class RoleResponse(BaseModel):
    """Role record including its permission keys."""

    id: int
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]

    model_config = {"from_attributes": True}


class RoleCreateRequest(BaseModel):
    """Payload for creating or updating a role."""

    name: str
    description: str | None = None
    permission_keys: list[str] = []


class InviteRequest(BaseModel):
    """Payload for inviting a new user by email."""

    email: str
    first_name: str | None = None
    last_name: str | None = None
    department: str | None = None
    role_id: int | None = None
