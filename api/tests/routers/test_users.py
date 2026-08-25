"""Unit tests for self-service profile, password change, avatars, and directory.

The password-change and avatar-serving paths carry the weight here: one guards a
credential on a live session, the other builds an object-storage key out of a URL
path segment.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.middleware.auth import CurrentUser
from app.routers.users import (
    PasswordChange,
    ProfileUpdate,
    change_my_password,
    delete_my_avatar,
    get_my_profile,
    list_directory,
    serve_avatar,
    update_my_profile,
    upload_my_avatar,
)


def _make_user(user_id: int = 1, *, hashed_password: str | None = "hashed") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.org_id = 1
    user.email = "person@example.com"
    user.display_name = "Person"
    user.first_name = None
    user.last_name = None
    user.job_title = None
    user.department = None
    user.phone_number = None
    user.timezone = None
    user.avatar_url = None
    user.user_type = None
    user.totp_enabled = False
    user.hashed_password = hashed_password
    return user


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _session(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _user() -> CurrentUser:
    return CurrentUser(user_id=1, org_id=1, role="analyst", email="person@example.com")


def _png_upload(content: bytes = b"x" * 200, content_type: str = "image/png") -> UploadFile:
    return UploadFile(
        filename="a.png", file=io.BytesIO(content), headers={"content-type": content_type}
    )


# ---------------------------------------------------------------------------
# Reading and editing your own profile
# ---------------------------------------------------------------------------


class TestGetMyProfile:
    @pytest.mark.asyncio
    async def test_returns_the_callers_own_record(self) -> None:
        db = _session(_scalar_result(_make_user()), _rows_result([("analyst",)]))

        result = await get_my_profile(current_user=_user(), db=db)

        assert (result.email, result.roles) == ("person@example.com", ["analyst"])

    @pytest.mark.asyncio
    async def test_sso_account_reports_no_password(self) -> None:
        """The UI hides the change-password form when there is nothing to change."""
        db = _session(_scalar_result(_make_user(hashed_password=None)), _rows_result([]))

        result = await get_my_profile(current_user=_user(), db=db)

        assert result.has_password is False


class TestUpdateMyProfile:
    @pytest.mark.asyncio
    async def test_sets_a_supplied_field(self) -> None:
        user = _make_user()
        db = _session(_scalar_result(user), _rows_result([]))

        await update_my_profile(
            ProfileUpdate(job_title="Analyst"), current_user=_user(), db=db
        )

        assert user.job_title == "Analyst"

    @pytest.mark.asyncio
    async def test_omitted_field_is_left_alone(self) -> None:
        """A partial save must not blank out everything it did not mention."""
        user = _make_user()
        user.display_name = "Keep Me"
        db = _session(_scalar_result(user), _rows_result([]))

        await update_my_profile(
            ProfileUpdate(job_title="Analyst"), current_user=_user(), db=db
        )

        assert user.display_name == "Keep Me"

    @pytest.mark.asyncio
    async def test_explicit_null_clears_a_field(self) -> None:
        user = _make_user()
        user.job_title = "Old Title"
        db = _session(_scalar_result(user), _rows_result([]))

        await update_my_profile(
            ProfileUpdate(job_title=None), current_user=_user(), db=db
        )

        assert user.job_title is None

    @pytest.mark.asyncio
    async def test_a_cleared_form_field_becomes_null_not_empty_string(self) -> None:
        user = _make_user()
        user.job_title = "Old Title"
        db = _session(_scalar_result(user), _rows_result([]))

        await update_my_profile(ProfileUpdate(job_title="   "), current_user=_user(), db=db)

        assert user.job_title is None

    @pytest.mark.asyncio
    async def test_surrounding_whitespace_is_trimmed(self) -> None:
        user = _make_user()
        db = _session(_scalar_result(user), _rows_result([]))

        await update_my_profile(
            ProfileUpdate(display_name="  Ada Lovelace  "), current_user=_user(), db=db
        )

        assert user.display_name == "Ada Lovelace"

    @pytest.mark.asyncio
    async def test_bill_rate_is_not_a_self_editable_field(self) -> None:
        """Rates and capacity drive billing, so they stay on the admin API."""
        assert "default_bill_rate" not in ProfileUpdate.model_fields
        assert "weekly_capacity_hours" not in ProfileUpdate.model_fields
        assert "is_active" not in ProfileUpdate.model_fields


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


class TestChangeMyPassword:
    @pytest.mark.asyncio
    async def test_correct_current_password_rehashes(self) -> None:
        user = _make_user()
        db = _session(_scalar_result(user))

        with (
            patch("app.routers.users.verify_password", return_value=True),
            patch("app.routers.users.hash_password", return_value="new-hash"),
        ):
            await change_my_password(
                PasswordChange(
                    current_password="old-password", new_password="a-brand-new-secret"
                ),
                current_user=_user(),
                db=db,
            )

        assert user.hashed_password == "new-hash"

    @pytest.mark.asyncio
    async def test_wrong_current_password_is_rejected(self) -> None:
        user = _make_user()
        db = _session(_scalar_result(user))

        with (
            patch("app.routers.users.verify_password", return_value=False),
            pytest.raises(HTTPException) as exc,
        ):
            await change_my_password(
                PasswordChange(current_password="guess", new_password="a-brand-new-secret"),
                current_user=_user(),
                db=db,
            )

        assert exc.value.status_code == 400
        assert user.hashed_password == "hashed"

    @pytest.mark.asyncio
    async def test_short_new_password_is_rejected(self) -> None:
        db = _session(_scalar_result(_make_user()))

        with (
            patch("app.routers.users.verify_password", return_value=True),
            pytest.raises(HTTPException) as exc,
        ):
            await change_my_password(
                PasswordChange(current_password="old-password", new_password="short"),
                current_user=_user(),
                db=db,
            )

        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_reusing_the_current_password_is_rejected(self) -> None:
        db = _session(_scalar_result(_make_user()))

        with (
            patch("app.routers.users.verify_password", return_value=True),
            pytest.raises(HTTPException) as exc,
        ):
            await change_my_password(
                PasswordChange(
                    current_password="the-same-password", new_password="the-same-password"
                ),
                current_user=_user(),
                db=db,
            )

        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_sso_only_account_gets_an_explanation(self) -> None:
        db = _session(_scalar_result(_make_user(hashed_password=None)))

        with pytest.raises(HTTPException) as exc:
            await change_my_password(
                PasswordChange(current_password="x", new_password="a-brand-new-secret"),
                current_user=_user(),
                db=db,
            )

        assert exc.value.status_code == 400
        assert "identity provider" in exc.value.detail


# ---------------------------------------------------------------------------
# API keys are not people
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Avatars
# ---------------------------------------------------------------------------


class TestUploadAvatar:
    @pytest.mark.asyncio
    async def test_stored_url_points_at_the_serving_route(self) -> None:
        user = _make_user()
        db = _session(_scalar_result(user))

        with patch("app.storage.get_filesystem") as filesystem:
            filesystem.return_value._pipe_file = AsyncMock()
            result = await upload_my_avatar(file=_png_upload(), current_user=_user(), db=db)

        assert result["avatar_url"].startswith("/users/1/avatar/")
        assert user.avatar_url == result["avatar_url"]

    @pytest.mark.asyncio
    async def test_svg_is_rejected(self) -> None:
        """An SVG can carry script and these are served from our own origin."""
        db = _session(_scalar_result(_make_user()))

        with pytest.raises(HTTPException) as exc:
            await upload_my_avatar(
                file=_png_upload(content_type="image/svg+xml"), current_user=_user(), db=db
            )

        assert exc.value.status_code == 415

    @pytest.mark.asyncio
    async def test_oversized_image_is_rejected(self) -> None:
        from app.services.avatars import MAX_AVATAR_BYTES

        db = _session(_scalar_result(_make_user()))

        with pytest.raises(HTTPException) as exc:
            await upload_my_avatar(
                file=_png_upload(content=b"x" * (MAX_AVATAR_BYTES + 1)),
                current_user=_user(),
                db=db,
            )

        assert exc.value.status_code == 413

    @pytest.mark.asyncio
    async def test_empty_upload_is_rejected(self) -> None:
        db = _session(_scalar_result(_make_user()))

        with pytest.raises(HTTPException) as exc:
            await upload_my_avatar(file=_png_upload(content=b""), current_user=_user(), db=db)

        assert exc.value.status_code == 400


class TestDeleteAvatar:
    @pytest.mark.asyncio
    async def test_clears_the_pointer_so_initials_take_over(self) -> None:
        user = _make_user()
        user.avatar_url = "/users/1/avatar/abc.png"
        db = _session(_scalar_result(user))

        await delete_my_avatar(current_user=_user(), db=db)

        assert user.avatar_url is None


class TestServeAvatar:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "filename",
        [
            pytest.param("../../../../etc/passwd", id="traversal"),
            pytest.param("a" * 32 + ".svg", id="disallowed-extension"),
            pytest.param("short.png", id="not-a-uuid"),
            pytest.param("A" * 32 + ".png", id="uppercase-hex"),
        ],
    )
    async def test_malformed_filename_is_404_before_any_lookup(self, filename: str) -> None:
        db = _session()

        with pytest.raises(HTTPException) as exc:
            await serve_avatar(1, filename, db=db)

        assert exc.value.status_code == 404
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_user_is_404(self) -> None:
        db = _session(_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await serve_avatar(999, "a" * 32 + ".png", db=db)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_object_is_404_rather_than_a_500(self) -> None:
        db = _session(_scalar_result(1))

        with patch("app.storage.get_filesystem") as filesystem:
            filesystem.return_value._cat_file = AsyncMock(side_effect=FileNotFoundError)
            with pytest.raises(HTTPException) as exc:
                await serve_avatar(1, "a" * 32 + ".png", db=db)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_served_with_the_matching_media_type(self) -> None:
        db = _session(_scalar_result(1))

        with patch("app.storage.get_filesystem") as filesystem:
            filesystem.return_value._cat_file = AsyncMock(return_value=b"bytes")
            response = await serve_avatar(1, "b" * 32 + ".webp", db=db)

        assert response.media_type == "image/webp"

    @pytest.mark.asyncio
    async def test_org_comes_from_the_user_not_the_request(self) -> None:
        """The storage key is built server-side, so a caller cannot pick the org."""
        db = _session(_scalar_result(42))

        with patch("app.storage.get_filesystem") as filesystem, patch(
            "app.storage.get_storage_path", side_effect=lambda key: key
        ) as path:
            filesystem.return_value._cat_file = AsyncMock(return_value=b"bytes")
            await serve_avatar(1, "c" * 32 + ".png", db=db)

        assert path.call_args[0][0] == f"avatars/org_42/user_1/{'c' * 32}.png"


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------


class TestDirectory:
    @pytest.mark.asyncio
    async def test_returns_picker_fields_for_active_users(self) -> None:
        db = _session(
            _rows_result([(3, "Ada", "ada@example.com", "Engineer", "/users/3/avatar/x.png")])
        )

        result = await list_directory(current_user=_user(), db=db)

        assert result[0].model_dump() == {
            "user_id": 3,
            "display_name": "Ada",
            "email": "ada@example.com",
            "job_title": "Engineer",
            "avatar_url": "/users/3/avatar/x.png",
        }

    @pytest.mark.asyncio
    async def test_exposes_nothing_beyond_what_a_picker_renders(self) -> None:
        """Phone, rate, capacity, and active status stay on the admin API."""
        from app.routers.users import DirectoryEntry

        assert set(DirectoryEntry.model_fields) == {
            "user_id",
            "display_name",
            "email",
            "job_title",
            "avatar_url",
        }
