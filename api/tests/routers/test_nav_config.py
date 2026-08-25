"""Tests for the admin-authored portal navigation: validation and the endpoints.

The saved navigation is rendered into an anchor for every user in the
organisation, so what the schema refuses matters more than what it accepts — an
unchecked ``javascript:`` href would be stored XSS.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.middleware.auth import CurrentUser
from app.models.org_settings import OrgSettings
from app.routers import admin
from app.schemas.nav_config import MAX_CHILDREN, MAX_ITEMS, NavConfigRequest, NavItem


def link(**overrides: object) -> dict:
    return {"type": "link", "label": "Dashboards", "href": "/dashboard", **overrides}


def dropdown(**overrides: object) -> dict:
    return {
        "type": "dropdown",
        "label": "Reports",
        "items": [{"label": "Sales", "href": "/dashboard/1"}],
        **overrides,
    }


def result_with(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


class TestHrefValidation:
    """An href is an allow-list of two shapes, not a string that looks like a URL."""

    @pytest.mark.parametrize(
        "href",
        [
            "/dashboard",
            "/dashboard/12",
            "/pages/quarterly-review",
            "/data-dicts/3",
            "/exports?status=failed",
            "/pages/a-b_c.d",
            "https://example.com/report",
            "http://intranet.local:8080/x",
            "HTTPS://EXAMPLE.COM",
        ],
    )
    def test_internal_paths_and_http_urls_are_accepted(self, href: str) -> None:
        assert NavItem.model_validate(link(href=href)).href == href

    @pytest.mark.parametrize(
        ("href", "why"),
        [
            ("javascript:alert(1)", "executes in the page"),
            ("JavaScript:alert(1)", "executes, and case is not a defence"),
            ("  javascript:alert(1)  ", "executes once trimmed"),
            ("data:text/html;base64,PHNjcmlwdD4=", "executes as a document"),
            ("vbscript:msgbox(1)", "executes"),
            ("//evil.example.com", "protocol-relative — reads local, goes off-site"),
            ("file:///etc/passwd", "not a web link"),
            ("dashboard", "relative, so it resolves against wherever the user is"),
            ("", "no target at all"),
            ("   ", "no target at all"),
        ],
    )
    def test_dangerous_or_ambiguous_hrefs_are_refused(self, href: str, why: str) -> None:
        with pytest.raises(ValidationError):
            NavItem.model_validate(link(href=href))

    def test_a_dropdown_child_href_is_validated_the_same_way(self) -> None:
        # The child links are the ones an admin pastes in bulk, so they are more
        # likely to carry something odd — not less.
        with pytest.raises(ValidationError):
            NavItem.model_validate(
                dropdown(items=[{"label": "Bad", "href": "javascript:alert(1)"}])
            )

    def test_an_href_is_stored_trimmed(self) -> None:
        assert NavItem.model_validate(link(href="  /dashboard/7  ")).href == "/dashboard/7"


class TestItemShape:
    """An item's fields have to match its type, or the nav renders broken."""

    def test_a_link_needs_a_target(self) -> None:
        with pytest.raises(ValidationError, match="needs a target"):
            NavItem.model_validate({"type": "link", "label": "Nowhere"})

    def test_a_link_cannot_also_hold_items(self) -> None:
        # Ambiguous: the renderer would have to guess whether to make it a
        # dropdown or a link, and the two behave differently.
        with pytest.raises(ValidationError, match="cannot also hold items"):
            NavItem.model_validate(link(items=[{"label": "x", "href": "/x"}]))

    def test_a_dropdown_needs_at_least_one_item(self) -> None:
        with pytest.raises(ValidationError, match="needs at least one item"):
            NavItem.model_validate({"type": "dropdown", "label": "Empty", "items": []})

    def test_a_dropdown_cannot_also_have_its_own_target(self) -> None:
        with pytest.raises(ValidationError, match="cannot also have its own target"):
            NavItem.model_validate(dropdown(href="/dashboard"))

    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            NavItem.model_validate({"type": "megamenu", "label": "x", "href": "/x"})

    def test_a_blank_label_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            NavItem.model_validate(link(label="   "))

    def test_a_label_is_stored_trimmed(self) -> None:
        assert NavItem.model_validate(link(label="  Sales  ")).label == "Sales"


class TestSizeLimits:
    """The config is read on every page load, so its size is bounded."""

    def test_a_navigation_at_the_limit_is_accepted(self) -> None:
        request = NavConfigRequest.model_validate({"items": [link()] * MAX_ITEMS})

        assert len(request.items) == MAX_ITEMS

    def test_one_item_past_the_limit_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            NavConfigRequest.model_validate({"items": [link()] * (MAX_ITEMS + 1)})

    def test_a_dropdown_past_the_child_limit_is_refused(self) -> None:
        children = [{"label": "x", "href": "/x"}] * (MAX_CHILDREN + 1)

        with pytest.raises(ValidationError):
            NavItem.model_validate(dropdown(items=children))

    def test_an_empty_navigation_is_valid(self) -> None:
        # It is how an admin asks for the defaults back, not an error.
        assert NavConfigRequest.model_validate({"items": []}).items == []


class TestGetNavConfig:
    @pytest.mark.asyncio
    async def test_an_unset_navigation_reads_as_empty_rather_than_404(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # Using the defaults is a normal state, not a missing resource.
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_with(None))

        response = await admin.get_nav_config(mock_admin_user, db)

        assert response.items == []

    @pytest.mark.asyncio
    async def test_a_saved_navigation_is_returned(self, mock_admin_user: CurrentUser) -> None:
        row = SimpleNamespace(org_id=1, nav_config=[link(), dropdown()])
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_with(row))

        response = await admin.get_nav_config(mock_admin_user, db)

        assert [item.type for item in response.items] == ["link", "dropdown"]


class TestUpdateNavConfig:
    @pytest.mark.asyncio
    async def test_saving_stores_the_items(self, mock_admin_user: CurrentUser) -> None:
        row = SimpleNamespace(org_id=1, nav_config=None)
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=result_with(row))
        request = NavConfigRequest.model_validate({"items": [link()]})

        with (
            patch.object(admin.ledger, "log_update", AsyncMock()),
            patch.object(admin.ledger, "serialize_row", MagicMock(return_value={})),
        ):
            await admin.update_nav_config(request, mock_admin_user, db)

        assert row.nav_config == [{"type": "link", "label": "Dashboards", "href": "/dashboard"}]

    @pytest.mark.asyncio
    async def test_an_empty_navigation_is_stored_as_null(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # One representation of "use the defaults" rather than two, so the
        # renderer does not have to treat [] and null as the same thing.
        row = SimpleNamespace(org_id=1, nav_config=[link()])
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=result_with(row))

        with (
            patch.object(admin.ledger, "log_update", AsyncMock()),
            patch.object(admin.ledger, "serialize_row", MagicMock(return_value={})),
        ):
            await admin.update_nav_config(
                NavConfigRequest.model_validate({"items": []}), mock_admin_user, db
            )

        assert row.nav_config is None

    @pytest.mark.asyncio
    async def test_a_dropdown_is_stored_without_a_null_href(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # exclude_none keeps `"href": null` out of the stored JSON — the prune
        # walks these dicts, and an explicit null is one more shape to handle.
        row = SimpleNamespace(org_id=1, nav_config=None)
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=result_with(row))

        with (
            patch.object(admin.ledger, "log_update", AsyncMock()),
            patch.object(admin.ledger, "serialize_row", MagicMock(return_value={})),
        ):
            await admin.update_nav_config(
                NavConfigRequest.model_validate({"items": [dropdown()]}), mock_admin_user, db
            )

        assert "href" not in row.nav_config[0]

    @pytest.mark.asyncio
    async def test_saving_is_recorded_in_the_change_ledger(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # The navigation is org-wide and easy to get wrong, so it is the kind of
        # change someone needs to be able to undo.
        row = SimpleNamespace(org_id=1, nav_config=None)
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=result_with(row))

        with (
            patch.object(admin.ledger, "log_update", AsyncMock()) as log_update,
            patch.object(
                admin.ledger, "serialize_row", MagicMock(return_value={"nav_config": None})
            ),
        ):
            await admin.update_nav_config(
                NavConfigRequest.model_validate({"items": [link()]}), mock_admin_user, db
            )

        assert log_update.await_args.kwargs["resource_type"] == "org_settings"
        assert log_update.await_args.kwargs["before"] == {"nav_config": None}

    @pytest.mark.asyncio
    async def test_a_missing_settings_row_is_created(self, mock_admin_user: CurrentUser) -> None:
        # A fresh org has no org_settings row, and saving a navigation must not
        # be the one action that needs an operator to seed one first.
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=result_with(None))

        with (
            patch.object(admin.ledger, "log_update", AsyncMock()),
            patch.object(admin.ledger, "serialize_row", MagicMock(return_value={})),
        ):
            await admin.update_nav_config(
                NavConfigRequest.model_validate({"items": [link()]}), mock_admin_user, db
            )

        # Not a bare add-count: audit_action adds its own row to the session.
        added = [call.args[0] for call in db.add.call_args_list]
        assert any(isinstance(obj, OrgSettings) for obj in added)
