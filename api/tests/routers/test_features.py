"""Unit tests for feature flag endpoints and config env var override logic."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Config — feature_overrides property
# ---------------------------------------------------------------------------


class TestFeatureOverrides:
    """Tests for settings.feature_overrides — reads FEATURE_* env vars at call time."""

    def test_no_env_vars_returns_empty(self) -> None:
        """feature_overrides is empty when no FEATURE_* vars are set."""
        from app.config import settings

        # Ensure none of the known vars are set
        for env_var in ["FEATURE_DASHBOARDS", "FEATURE_EXPORTS", "FEATURE_GOVERNANCE"]:
            os.environ.pop(env_var, None)

        overrides = settings.feature_overrides
        assert "dashboards" not in overrides
        assert "exports" not in overrides

    def test_true_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FEATURE_DASHBOARDS=true sets overrides['dashboards'] = True."""
        monkeypatch.setenv("FEATURE_DASHBOARDS", "true")
        from app.config import settings

        assert settings.feature_overrides.get("dashboards") is True

    def test_false_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FEATURE_EXPORTS=false sets overrides['exports'] = False."""
        monkeypatch.setenv("FEATURE_EXPORTS", "false")
        from app.config import settings

        assert settings.feature_overrides.get("exports") is False

    def test_numeric_one_is_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEATURE_GOVERNANCE", "1")
        from app.config import settings

        assert settings.feature_overrides.get("governance") is True

    def test_zero_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEATURE_CUSTOM_PAGES", "0")
        from app.config import settings

        assert settings.feature_overrides.get("custom_pages") is False

    def test_dotted_key_embed_powerbi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FEATURE_EMBED_POWERBI maps to key 'embed.powerbi'."""
        monkeypatch.setenv("FEATURE_EMBED_POWERBI", "false")
        from app.config import settings

        assert settings.feature_overrides.get("embed.powerbi") is False

    def test_multiple_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEATURE_DASHBOARDS", "true")
        monkeypatch.setenv("FEATURE_EXPORTS", "false")
        monkeypatch.setenv("FEATURE_PIPELINES_ADF", "true")
        from app.config import settings

        overrides = settings.feature_overrides
        assert overrides["dashboards"] is True
        assert overrides["exports"] is False
        assert overrides["pipelines.adf"] is True


# ---------------------------------------------------------------------------
# list_features endpoint
# ---------------------------------------------------------------------------


class TestListFeatures:
    """Tests for GET /admin/features."""

    @pytest.mark.asyncio
    async def test_returns_db_flags_when_no_env_override(
        self,
        mock_admin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns the DB-stored enabled state when no env var is set."""
        from app.models.feature_flag import FeatureFlag
        from app.routers.admin import list_features

        # Ensure no env var override for chat
        monkeypatch.delenv("FEATURE_PIPELINES", raising=False)

        pipelines_flag = MagicMock(spec=FeatureFlag)
        pipelines_flag.feature_key = "pipelines"
        pipelines_flag.enabled = True
        pipelines_flag.config = None

        scalars_result = MagicMock()
        scalars_result.all.return_value = [pipelines_flag]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db_session.execute = AsyncMock(return_value=execute_result)

        result = await list_features(
            current_user=mock_admin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        pipelines_entry = next((f for f in result if f["feature_key"] == "pipelines"), None)
        assert pipelines_entry is not None
        assert pipelines_entry["enabled"] is True
        assert pipelines_entry["env_override"] is False

    @pytest.mark.asyncio
    async def test_env_override_replaces_db_value(
        self,
        mock_admin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When FEATURE_PIPELINES=false, the flag is returned as disabled regardless of DB."""
        from app.models.feature_flag import FeatureFlag
        from app.routers.admin import list_features

        monkeypatch.setenv("FEATURE_PIPELINES", "false")

        pipelines_flag = MagicMock(spec=FeatureFlag)
        pipelines_flag.feature_key = "pipelines"
        pipelines_flag.enabled = True  # DB says enabled...
        pipelines_flag.config = None

        scalars_result = MagicMock()
        scalars_result.all.return_value = [pipelines_flag]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db_session.execute = AsyncMock(return_value=execute_result)

        result = await list_features(
            current_user=mock_admin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        pipelines_entry = next((f for f in result if f["feature_key"] == "pipelines"), None)
        assert pipelines_entry is not None
        assert pipelines_entry["enabled"] is False  # ...but env var overrides it
        assert pipelines_entry["env_override"] is True

    @pytest.mark.asyncio
    async def test_all_known_keys_present_when_db_empty(
        self,
        mock_admin_user: object,
        mock_db_session: AsyncMock,
    ) -> None:
        """Every known feature key appears even when the DB has no rows."""
        from app.config import FEATURE_ENV_VARS
        from app.routers.admin import list_features

        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db_session.execute = AsyncMock(return_value=execute_result)

        result = await list_features(
            current_user=mock_admin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        returned_keys = {f["feature_key"] for f in result}
        for key in FEATURE_ENV_VARS:
            assert key in returned_keys, f"Expected key '{key}' in response"

    @pytest.mark.asyncio
    async def test_missing_db_flag_defaults_to_false(
        self,
        mock_admin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A key not in the DB and with no env override defaults to enabled=False."""
        monkeypatch.delenv("FEATURE_GOVERNANCE", raising=False)

        from app.routers.admin import list_features

        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db_session.execute = AsyncMock(return_value=execute_result)

        result = await list_features(
            current_user=mock_admin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        gov_entry = next((f for f in result if f["feature_key"] == "governance"), None)
        assert gov_entry is not None
        assert gov_entry["enabled"] is False


# ---------------------------------------------------------------------------
# toggle_feature endpoint
# ---------------------------------------------------------------------------


class TestToggleFeature:
    """Tests for PUT /admin/features/{key}."""

    @pytest.mark.asyncio
    async def test_creates_flag_when_not_in_db(
        self,
        mock_superadmin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Creates a new FeatureFlag row when the key doesn't exist yet."""
        from app.routers.admin import FeatureToggleRequest, toggle_feature

        monkeypatch.delenv("FEATURE_RETENTION", raising=False)

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=scalar_result)

        result = await toggle_feature(
            key="retention",
            data=FeatureToggleRequest(enabled=True),
            current_user=mock_superadmin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        assert result["feature_key"] == "retention"
        assert result["enabled"] is True
        assert result["env_override"] is False
        # The flag row is added (an audit log row is also added alongside it).
        assert mock_db_session.add.called
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_flag(
        self,
        mock_superadmin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Updates the enabled field on an existing FeatureFlag row."""
        from app.models.feature_flag import FeatureFlag
        from app.routers.admin import FeatureToggleRequest, toggle_feature

        monkeypatch.delenv("FEATURE_BACKUPS", raising=False)

        existing = MagicMock(spec=FeatureFlag)
        existing.enabled = True
        existing.updated_by_user_id = None

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = existing
        mock_db_session.execute = AsyncMock(return_value=scalar_result)

        result = await toggle_feature(
            key="exports",
            data=FeatureToggleRequest(enabled=False),
            current_user=mock_superadmin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        assert existing.enabled is False
        assert result["enabled"] is False
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_effective_value_is_env_when_override_set(
        self,
        mock_superadmin_user: object,
        mock_db_session: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When env var is set the response shows the env value, not the requested value."""
        from app.models.feature_flag import FeatureFlag
        from app.routers.admin import FeatureToggleRequest, toggle_feature

        monkeypatch.setenv("FEATURE_EXPORTS", "true")  # env says enabled

        existing = MagicMock(spec=FeatureFlag)
        existing.enabled = True
        existing.updated_by_user_id = None

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = existing
        mock_db_session.execute = AsyncMock(return_value=scalar_result)

        result = await toggle_feature(
            key="exports",
            data=FeatureToggleRequest(enabled=False),  # tries to disable...
            current_user=mock_superadmin_user,  # type: ignore[arg-type]
            db=mock_db_session,
        )

        # ...but effective value is the env var (True)
        assert result["enabled"] is True
        assert result["env_override"] is True
