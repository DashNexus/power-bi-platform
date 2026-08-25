"""Tests for the mutation registry: what is registered, and who may revert it.

The registry is what makes a resource appear in `/changes` and be revertible, so
the two things worth pinning are that a resource is registered at all and that
its guards match the visibility rule its own router enforces. A guard that is
looser than the router turns the change feed into a way around it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.middleware.auth import CurrentUser
from app.models.export import ExportSchedule
from app.services import mutation_registry as registry


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture()
def report_resource() -> registry.MutationResource:
    resource = registry.get_resource("report")
    assert resource is not None
    return resource


class TestReportRegistration:
    """Reports are registered, so a change to one shows on /admin/changes."""

    def test_report_is_registered_against_the_schedule_model(
        self, report_resource: registry.MutationResource
    ) -> None:
        assert report_resource.model is ExportSchedule

    def test_a_report_is_named_by_its_name(
        self, report_resource: registry.MutationResource
    ) -> None:
        assert report_resource.resource_name(SimpleNamespace(name="Weekly orders")) == (
            "Weekly orders"
        )

    def test_report_carries_a_pre_delete_hook(
        self, report_resource: registry.MutationResource
    ) -> None:
        # Every run points back at its report with a NO ACTION foreign key, so
        # undoing a create fails on the constraint unless the runs are detached
        # first.
        assert report_resource.pre_delete is not None

    @pytest.mark.asyncio
    async def test_the_pre_delete_hook_detaches_the_run_history(
        self, report_resource: registry.MutationResource
    ) -> None:
        db = AsyncMock()

        assert report_resource.pre_delete is not None
        await report_resource.pre_delete(db, SimpleNamespace(id=9))

        assert db.execute.await_count == 1


class TestReportGuards:
    """A report is private to its author, and the ledger inherits that.

    `routers/exports.py::_load_report` scopes by user_id with no admin bypass.
    If the guard here were looser, /changes would be a way to read and revert
    someone else's report.
    """

    @pytest.mark.asyncio
    async def test_the_owner_is_allowed(
        self, report_resource: registry.MutationResource
    ) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(SimpleNamespace(user_id=2)))
        owner = CurrentUser(user_id=2, org_id=1, role="analyst", email="a@example.com")

        await report_resource.require_edit(db, owner, 7, None)

    @pytest.mark.asyncio
    async def test_another_user_is_refused(
        self, report_resource: registry.MutationResource
    ) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(SimpleNamespace(user_id=2)))
        other = CurrentUser(user_id=3, org_id=1, role="analyst", email="b@example.com")

        with pytest.raises(HTTPException) as exc:
            await report_resource.require_view(db, other, 7, None)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_an_admin_is_refused_someone_elses_report(
        self, report_resource: registry.MutationResource, mock_admin_user: CurrentUser
    ) -> None:
        # Deliberate: nothing in this build shares a report, and a report holds
        # SQL and a delivery destination its author chose. An admin sees *that*
        # it changed in the feed, and reverts only their own.
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(SimpleNamespace(user_id=99)))

        with pytest.raises(HTTPException):
            await report_resource.require_edit(db, mock_admin_user, 7, None)

    @pytest.mark.asyncio
    async def test_ownership_is_read_from_the_snapshot_when_the_row_is_gone(
        self, report_resource: registry.MutationResource
    ) -> None:
        # Reverting a delete runs with no row to look at, so the guard has to
        # fall back to the stored snapshot or it could never allow the revert.
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        owner = CurrentUser(user_id=2, org_id=1, role="analyst", email="a@example.com")

        await report_resource.require_edit(db, owner, None, {"user_id": 2})

    @pytest.mark.asyncio
    async def test_an_unknown_owner_denies_rather_than_allows(
        self, report_resource: registry.MutationResource
    ) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        user = CurrentUser(user_id=2, org_id=1, role="analyst", email="a@example.com")

        with pytest.raises(HTTPException):
            await report_resource.require_edit(db, user, None, None)


class TestTopLevelResources:
    """The change feed's filter menu is built from the registry, not restated.

    It used to be a hand-written list in the client, which had drifted to offer
    resources this build does not have while omitting the ones it does.
    """

    def test_reports_are_offered(self) -> None:
        assert ("report", "SQL reports") in registry.top_level_resources()

    def test_child_resources_are_not_offered(self) -> None:
        # Registered so a deleted parent reverts complete — nobody filters a
        # change feed by "dashboard filter".
        offered = {value for value, _ in registry.top_level_resources()}

        assert "dashboard_filter" not in offered
        assert "dashboard_permission" not in offered
        assert "custom_page_permission" not in offered

    def test_every_offered_type_is_actually_registered(self) -> None:
        # An option the feed cannot filter by is worse than a missing one: it
        # returns an empty list that reads as "nothing ever happened".
        for value, _ in registry.top_level_resources():
            assert registry.get_resource(value) is not None

    def test_every_option_has_a_label(self) -> None:
        assert all(label for _, label in registry.top_level_resources())

    def test_the_list_is_stable(self) -> None:
        # Ordering the menu by chance means it reshuffles between deploys.
        offered = registry.top_level_resources()

        assert offered == sorted(offered)
