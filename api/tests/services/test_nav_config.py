"""Tests for keeping the portal navigation free of links to deleted resources.

Nothing ties a nav href to a live row, so deleting the dashboard behind a link
leaves every user in the organisation with a nav entry that 404s and no way to
tell why. These cover the prune that prevents it, and the id remap that lets a
reverted delete restore the link pointing at the right place.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import nav_config


def result_with(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def session_with(nav: list | None) -> tuple[AsyncMock, SimpleNamespace]:
    """Return (db, settings row) where the db yields that row."""
    row = SimpleNamespace(org_id=1, nav_config=nav)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_with(row))
    return db, row


class TestResourceHrefs:
    @pytest.mark.parametrize(
        ("kind", "identifier", "expected"),
        [
            ("dashboard", 7, ["/dashboard/7"]),
            ("custom_page", "quarterly", ["/pages/quarterly"]),
            ("warehouse_connection", 3, ["/data-dicts/3"]),
            ("data_pipeline", 2, ["/pipelines/2"]),
        ],
    )
    def test_each_kind_maps_to_its_route(
        self, kind: str, identifier: object, expected: list[str]
    ) -> None:
        assert nav_config.resource_hrefs(kind, identifier) == expected

    def test_an_unknown_kind_prunes_nothing_rather_than_guessing(self) -> None:
        # Guessing a route would delete a nav entry that has nothing to do with
        # the resource being removed.
        assert nav_config.resource_hrefs("spaceship", 1) == []


class TestPruneNavLinks:
    @pytest.mark.asyncio
    async def test_a_link_to_the_deleted_resource_is_removed(self) -> None:
        db, row = session_with(
            [
                {"type": "link", "label": "Sales", "href": "/dashboard/7"},
                {"type": "link", "label": "Home", "href": "/home"},
            ]
        )

        removed = await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert removed == ["/dashboard/7"]
        assert row.nav_config == [{"type": "link", "label": "Home", "href": "/home"}]

    @pytest.mark.asyncio
    async def test_matching_ignores_a_trailing_slash_and_case(self) -> None:
        # The href is typed by hand, so "/Dashboard/7/" and "/dashboard/7" are
        # the same link as far as the person who wrote it is concerned.
        db, row = session_with([{"type": "link", "label": "Sales", "href": "/Dashboard/7/"}])

        removed = await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert removed == ["/Dashboard/7/"]
        assert row.nav_config is None

    @pytest.mark.asyncio
    async def test_a_similar_href_is_left_alone(self) -> None:
        # /dashboard/70 starts with /dashboard/7 as a string; substring matching
        # here would silently delete an unrelated dashboard's link.
        db, row = session_with([{"type": "link", "label": "Other", "href": "/dashboard/70"}])

        removed = await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert removed == []
        assert row.nav_config == [{"type": "link", "label": "Other", "href": "/dashboard/70"}]

    @pytest.mark.asyncio
    async def test_a_child_link_inside_a_dropdown_is_pruned(self) -> None:
        db, row = session_with(
            [
                {
                    "type": "dropdown",
                    "label": "Reports",
                    "items": [
                        {"label": "Sales", "href": "/dashboard/7"},
                        {"label": "Costs", "href": "/dashboard/8"},
                    ],
                }
            ]
        )

        removed = await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert removed == ["/dashboard/7"]
        assert row.nav_config[0]["items"] == [{"label": "Costs", "href": "/dashboard/8"}]

    @pytest.mark.asyncio
    async def test_a_dropdown_emptied_by_the_prune_is_removed_too(self) -> None:
        # It would render as a menu that opens onto nothing.
        db, row = session_with(
            [
                {
                    "type": "dropdown",
                    "label": "Reports",
                    "items": [{"label": "Sales", "href": "/dashboard/7"}],
                }
            ]
        )

        await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert row.nav_config is None

    @pytest.mark.asyncio
    async def test_an_unaffected_navigation_is_left_untouched(self) -> None:
        nav = [{"type": "link", "label": "Home", "href": "/home"}]
        db, row = session_with(nav)

        removed = await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert removed == []
        assert row.nav_config == nav

    @pytest.mark.asyncio
    async def test_no_hrefs_means_no_query_at_all(self) -> None:
        # Deleting a resource with no nav route must not cost a round-trip on
        # every delete.
        db = AsyncMock()

        assert await nav_config.prune_nav_links(db, 1, []) == []
        assert db.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_an_org_with_no_settings_row_is_handled(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_with(None))

        assert await nav_config.prune_nav_links(db, 1, ["/dashboard/7"]) == []

    @pytest.mark.asyncio
    async def test_a_database_failure_never_blocks_the_delete(self) -> None:
        # A nav entry outliving its resource is cosmetic; failing someone's
        # delete over the cleanup is not.
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        assert await nav_config.prune_nav_links(db, 1, ["/dashboard/7"]) == []

    @pytest.mark.asyncio
    async def test_malformed_stored_items_are_kept_rather_than_dropped(self) -> None:
        # The column is JSON an older build could have written. Discarding what
        # this one does not recognise would quietly delete an admin's work.
        db, row = session_with(["not-a-dict", {"type": "link", "href": "/dashboard/7"}])

        await nav_config.prune_nav_links(db, 1, ["/dashboard/7"])

        assert row.nav_config == ["not-a-dict"]

    @pytest.mark.asyncio
    async def test_the_prune_joins_the_deletes_correlation_when_given_one(self) -> None:
        # So reverting the delete restores the nav entry with the resource,
        # rather than leaving the dashboard back but absent from the nav.
        db, _ = session_with([{"type": "link", "label": "Sales", "href": "/dashboard/7"}])
        ctx = object()

        with patch("app.services.change_ledger.log_update", AsyncMock()) as log_update:
            await nav_config.prune_nav_links(db, 1, ["/dashboard/7"], ctx=ctx)

        assert log_update.await_args.kwargs["ctx"] is ctx
        assert log_update.await_args.kwargs["resource_type"] == "org_settings"


class TestRemapNavIds:
    def test_an_href_follows_its_resources_new_id(self) -> None:
        # Recreating a deleted row assigns a fresh primary key, so a link
        # restored from the snapshot points at an id nothing has any more.
        row = SimpleNamespace(org_id=1, nav_config=[{"type": "link", "href": "/dashboard/7"}])

        nav_config.remap_nav_ids(row, {"dashboard": {7: 42}})

        assert row.nav_config == [{"type": "link", "href": "/dashboard/42"}]

    def test_a_child_href_is_remapped_too(self) -> None:
        row = SimpleNamespace(
            org_id=1,
            nav_config=[{"type": "dropdown", "items": [{"label": "S", "href": "/dashboard/7"}]}],
        )

        nav_config.remap_nav_ids(row, {"dashboard": {7: 42}})

        assert row.nav_config[0]["items"][0]["href"] == "/dashboard/42"

    def test_an_href_whose_id_did_not_change_is_untouched(self) -> None:
        nav = [{"type": "link", "href": "/dashboard/7"}]
        row = SimpleNamespace(org_id=1, nav_config=nav)

        nav_config.remap_nav_ids(row, {"dashboard": {9: 42}})

        assert row.nav_config == nav

    def test_a_non_resource_href_is_untouched(self) -> None:
        nav = [{"type": "link", "href": "/home"}, {"type": "link", "href": "https://x.test/7"}]
        row = SimpleNamespace(org_id=1, nav_config=list(nav))

        nav_config.remap_nav_ids(row, {"dashboard": {7: 42}})

        assert row.nav_config == nav

    def test_no_id_map_is_a_no_op(self) -> None:
        nav = [{"type": "link", "href": "/dashboard/7"}]
        row = SimpleNamespace(org_id=1, nav_config=nav)

        nav_config.remap_nav_ids(row, {})

        assert row.nav_config == nav
