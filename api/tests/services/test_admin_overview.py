"""Unit tests for the /admin overview aggregation.

Two things here are worth pinning: every count is org-scoped (an unfiltered
subquery would report other organisations' totals on an admin's landing page),
and they are all read in a single round trip, which is the only reason the page
can show three dozen numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.services import admin_overview

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _compile(stmt: object) -> str:
    """Render a statement as PostgreSQL SQL with literal parameters."""
    return str(
        stmt.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestCountSpecs:
    def test_every_count_filters_on_the_organisation(self) -> None:
        specs = admin_overview._count_specs(org_id=7, now=NOW)

        unscoped = [name for name, sq in specs.items() if "org_id = 7" not in _compile(sq)]

        assert unscoped == []

    def test_counts_compile_into_one_statement(self) -> None:
        specs = admin_overview._count_specs(org_id=1, now=NOW)

        sql = _compile(select(*(sq.label(name) for name, sq in specs.items())))

        assert sql.count("SELECT count(*)") == len(specs)
        assert "FROM" not in sql.split("SELECT count(*)")[0]

    def test_mfa_count_is_restricted_to_active_users(self) -> None:
        specs = admin_overview._count_specs(org_id=1, now=NOW)

        sql = _compile(specs["users_with_mfa"])

        # '= true', not 'IS true': T-SQL's IS accepts only NULL, so the
        # portable form goes through sql_compat.is_true (see that module).
        assert "users.is_active = true" in sql
        assert "users.totp_enabled = true" in sql


class TestLoadFeatures:
    @pytest.mark.asyncio
    async def test_env_override_wins_over_stored_value(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stored = MagicMock()
        stored.feature_key = "pipelines"
        stored.enabled = False
        result = MagicMock()
        result.scalars.return_value.all.return_value = [stored]
        mock_db_session.execute = AsyncMock(return_value=result)
        monkeypatch.setenv("FEATURE_PIPELINES", "true")

        summary = await admin_overview._load_features(mock_db_session, org_id=1)

        assert "pipelines" in summary["enabled_keys"]
        assert summary["env_overrides"] == 1

    @pytest.mark.asyncio
    async def test_key_with_no_row_counts_as_disabled(self, mock_db_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=result)

        summary = await admin_overview._load_features(mock_db_session, org_id=1)

        assert summary["enabled"] == 0
        assert summary["disabled"] == summary["total"]


class TestGetOverview:
    @pytest.mark.asyncio
    async def test_returns_every_section_in_six_queries(
        self, mock_db_session: AsyncMock
    ) -> None:
        counts = MagicMock()
        counts.one.return_value = MagicMock(
            _mapping=dict.fromkeys(admin_overview._count_specs(1, NOW), 3)
        )

        # `name` is a MagicMock constructor keyword, so it has to be set after
        # construction or the attribute reads back as a child mock.
        org_row = MagicMock(
            slug="acme",
            created_at=NOW,
            app_name="Acme BI",
            logo_url=None,
            audit_retention_days=30,
        )
        org_row.name = "Acme"
        org = MagicMock()
        org.first.return_value = org_row

        features = MagicMock()
        features.scalars.return_value.all.return_value = []

        mfa = MagicMock()
        mfa.scalar_one_or_none.return_value = None

        audit_log = MagicMock()
        audit_log.all.return_value = [
            (
                MagicMock(
                    id=1,
                    action="user.login",
                    resource_type=None,
                    resource_name=None,
                    created_at=NOW - timedelta(minutes=5),
                ),
                "ada@example.com",
                "Ada Lovelace",
            )
        ]

        changes = MagicMock()
        changes.all.return_value = []

        mock_db_session.execute = AsyncMock(
            side_effect=[counts, org, features, mfa, audit_log, changes]
        )

        payload = await admin_overview.get_overview(mock_db_session, org_id=1)

        assert set(payload) == {
            "org",
            "counts",
            "features",
            "auth",
            "recent_audit",
            "recent_changes",
            "active_window_days",
            "generated_at",
        }
        assert payload["org"]["name"] == "Acme"
        assert payload["counts"]["users_active"] == 3
        assert payload["recent_audit"][0]["user_name"] == "Ada Lovelace"
        assert mock_db_session.execute.await_count == 6

    @pytest.mark.asyncio
    async def test_missing_mfa_row_reports_optional_not_required(
        self, mock_db_session: AsyncMock
    ) -> None:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=result)

        auth = await admin_overview._load_auth(mock_db_session, org_id=1)

        assert auth["totp_required"] is False
        assert auth["totp_enabled"] is True
