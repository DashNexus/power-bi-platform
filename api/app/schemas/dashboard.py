"""Request and response models for dashboards and their filters.

``EmbedType`` is the allow-list this build ships: an authenticated **Power BI**
report, or a **page** embed — an ordinary URL in an iframe, with no credentials
and no token flow. Widening it means adding an embedder, not just a string.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

#: The embed technologies a dashboard may use.
EmbedType = Literal["powerbi", "page"]


class DashboardFilterSchema(BaseModel):
    """Schema for a single user-facing filter definition on a dashboard.

    Attributes:
        filter_key: Internal key used to apply the filter in the embed URL or query.
        filter_label: Human-readable label shown to the user.
        filter_type: Input type: 'string', 'date', 'number', or 'select'.
        default_value: Pre-populated value when the user has not interacted with
            the filter. None means the filter starts empty.
        user_attribute: When set, the filter is automatically populated from the
            authenticated user's session attribute (e.g. 'org_id', 'email').
        is_required: Whether the user must provide a value before viewing.
        display_order: Controls the order of filters in the UI (ascending).
    """

    filter_key: str
    filter_label: str
    filter_type: str  # 'string' | 'date' | 'number' | 'select'
    default_value: str | None = None
    user_attribute: str | None = None
    is_required: bool = False
    display_order: int = 0


class DashboardCreateRequest(BaseModel):
    """Request body for creating a new dashboard configuration.

    Attributes:
        name: Display name shown in the navigation and page title.
        description: Optional longer description for admin UIs and catalog.
        slug: URL-safe identifier, unique per organisation.
        embed_type: Embed technology — 'powerbi' or 'page'.
        settings: Embed-type-specific JSON config (workspace IDs, URLs, etc.).
        required_role: Minimum role to view this dashboard. Defaults to 'viewer'.
        filters: Ordered list of filter definitions for this dashboard.
    """

    name: str
    description: str | None = None
    slug: str
    # embed_type is derived server-side from the BI connection's provider when
    # bi_connection_id is set; sent directly only for page embeds.
    embed_type: EmbedType = "powerbi"
    bi_connection_id: int | None = None
    settings: dict[str, Any] = {}
    required_role: str = "viewer"
    tags: list[str] = []
    filters: list[DashboardFilterSchema] = []


class DashboardUpdateRequest(BaseModel):
    """Request body for partially updating a dashboard configuration.

    All fields are optional. Only supplied fields are updated.
    """

    name: str | None = None
    description: str | None = None
    embed_type: EmbedType | None = None
    bi_connection_id: int | None = None
    settings: dict[str, Any] | None = None
    required_role: str | None = None
    is_active: bool | None = None
    tags: list[str] | None = None


class DashboardResponse(BaseModel):
    """Response schema for a dashboard configuration.

    Returned by all dashboard read and write endpoints. Does not include
    internal fields (org_id, created_by_user_id).
    """

    id: int
    name: str
    description: str | None
    slug: str
    embed_type: EmbedType
    bi_connection_id: int | None = None
    # Resolved embed URL for page embeds (from settings.embed_url).
    embed_url: str = ""
    settings: dict[str, Any]
    required_role: str
    is_active: bool
    tags: list[str]
    filters: list[DashboardFilterSchema]

    model_config = {"from_attributes": True}


class DashboardPermissionRequest(BaseModel):
    """Request body for replacing a dashboard's access control list.

    Replaces all existing permissions for the dashboard. Pass empty lists
    to make a dashboard accessible to no one (admin-only).

    Attributes:
        user_ids: User IDs granted direct access.
        role_ids: Role IDs granted access — any user holding one of these roles
            will be able to view the dashboard.
    """

    user_ids: list[int] = []
    role_ids: list[int] = []


class PowerBIWorkspace(BaseModel):
    """A Power BI workspace (group) visible to the service principal."""

    id: str
    name: str


class PowerBIReport(BaseModel):
    """A Power BI report within a workspace."""

    id: str
    name: str
    workspace_id: str
    embed_url: str


class PowerBIEmbedFilter(BaseModel):
    """A resolved RLS filter to apply to the Power BI embed.

    Attributes:
        table: Power BI table name.
        column: Column name within the table.
        value: Resolved filter value — either a static admin-configured string
            or a user-session attribute resolved at token-generation time.
    """

    table: str
    column: str
    value: str


class PowerBIEmbedToken(BaseModel):
    """An Azure AD embed token for a Power BI report.

    Attributes:
        token: The short-lived embed token to pass to the Power BI JavaScript SDK.
        token_id: Azure-assigned identifier for this token.
        expiration: ISO 8601 expiry timestamp (UTC).
        embed_url: The report embed URL to pass alongside the token.
        embed_filters: Admin-configured RLS filters resolved at token-generation time.
            Applied to the report via the Power BI JS API before it renders.
    """

    token: str
    token_id: str
    expiration: str
    embed_url: str
    embed_filters: list[PowerBIEmbedFilter] = []
