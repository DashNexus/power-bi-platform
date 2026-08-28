"""Unit tests for issuing, classifying, and redeeming invitations.

The accept path carries the weight: it is unauthenticated, it creates an
account, and the only thing gating it is the token's own state. Every way that
state can say "no" — used, expired, already registered — is pinned here, along
with the naive-datetime comparison that would otherwise turn "expired" into a
500.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.invite import AcceptInviteRequest, InviteRequest
from app.services import invites as invite_svc


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _all_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _session(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


def _invite(
    *,
    invite_id: int = 3,
    email: str = "new@example.com",
    expires_in_days: int = 7,
    accepted: bool = False,
    role_id: int | None = None,
    aware: bool = True,
) -> MagicMock:
    now = datetime.now(UTC)
    expires = now + timedelta(days=expires_in_days)
    invite = MagicMock()
    invite.id = invite_id
    invite.org_id = 1
    invite.email = email
    invite.token = "tok-abc"
    invite.first_name = "Jane"
    invite.last_name = "Smith"
    invite.role_id = role_id
    invite.expires_at = expires if aware else expires.replace(tzinfo=None)
    invite.accepted_at = now if accepted else None
    invite.created_at = now
    return invite


# ---------------------------------------------------------------------------
# Links and status
# ---------------------------------------------------------------------------


class TestInviteUrl:
    def test_builds_the_accept_link_from_the_configured_app_origin(self) -> None:
        with patch.object(invite_svc.settings, "nextauth_url", "https://bi.example.com"):
            assert (
                invite_svc.invite_url("abc123")
                == "https://bi.example.com/accept-invite?token=abc123"
            )

    def test_a_trailing_slash_on_the_origin_does_not_double(self) -> None:
        with patch.object(invite_svc.settings, "nextauth_url", "https://bi.example.com/"):
            assert invite_svc.invite_url("abc") == "https://bi.example.com/accept-invite?token=abc"


class TestInviteStatus:
    def test_an_open_invitation_is_pending(self) -> None:
        assert invite_svc.invite_status(_invite()) == "pending"

    def test_an_invitation_past_its_expiry_is_expired(self) -> None:
        assert invite_svc.invite_status(_invite(expires_in_days=-1)) == "expired"

    def test_acceptance_wins_over_expiry(self) -> None:
        # A used link stays "accepted" for ever; reporting it as expired would
        # offer Resend on an invitation that already produced an account.
        assert invite_svc.invite_status(_invite(expires_in_days=-30, accepted=True)) == "accepted"

    def test_a_naive_expiry_from_the_driver_still_compares(self) -> None:
        # A DateTime(timezone=True) column can come back naive from a session
        # that never round-tripped the database; comparing it to an aware "now"
        # raises TypeError, which reaches the invitee as a 500.
        assert invite_svc.invite_status(_invite(expires_in_days=-1, aware=False)) == "expired"


class TestToResponse:
    def test_carries_the_link_so_it_can_be_copied(self) -> None:
        with patch.object(invite_svc.settings, "nextauth_url", "https://bi.example.com"):
            response = invite_svc.to_response(_invite(), role_name="viewer")

        assert response.invite_url == "https://bi.example.com/accept-invite?token=tok-abc"
        assert response.role_name == "viewer"
        assert response.status == "pending"


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------


class TestCreateInvite:
    @pytest.mark.asyncio
    async def test_issues_a_token_expiring_in_a_week(self) -> None:
        db = _session(_scalar_result(None), MagicMock())

        invite = await invite_svc.create_invite(
            db, 1, 9, InviteRequest(email="new@example.com")
        )

        assert len(invite.token) > 20
        assert timedelta(days=6) < invite.expires_at - datetime.now(UTC) <= timedelta(days=7)

    @pytest.mark.asyncio
    async def test_normalises_the_address_before_storing_it(self) -> None:
        db = _session(_scalar_result(None), MagicMock())

        invite = await invite_svc.create_invite(
            db, 1, 9, InviteRequest(email="  New@Example.COM ")
        )

        assert invite.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_an_already_registered_address_is_refused(self) -> None:
        db = _session(_scalar_result(42))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.create_invite(db, 1, 9, InviteRequest(email="taken@example.com"))

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_supersedes_any_open_invitation_for_the_same_address(self) -> None:
        # Two live tokens for one mailbox makes "copy link" ambiguous: the link
        # the admin copies need not be the one in the invitee's inbox.
        db = _session(_scalar_result(None), MagicMock())

        await invite_svc.create_invite(db, 1, 9, InviteRequest(email="new@example.com"))

        assert "DELETE FROM user_invites" in str(db.execute.await_args_list[1].args[0])


class TestRefreshInvite:
    @pytest.mark.asyncio
    async def test_resending_mints_a_new_token(self) -> None:
        # A forwarded or archived link must stop working the moment an admin
        # resends, so the old token cannot be re-mailed.
        db = _session()
        invite = _invite()
        original = invite.token

        await invite_svc.refresh_invite(db, invite)

        assert invite.token != original
        assert invite.expires_at > datetime.now(UTC) + timedelta(days=6)


class TestLoadInvite:
    @pytest.mark.asyncio
    async def test_another_orgs_invitation_is_a_404(self) -> None:
        db = _session(_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.load_invite(db, 3, org_id=2)

        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class TestInviteEmail:
    def test_both_parts_carry_the_same_link(self) -> None:
        subject, text, html_body = invite_svc._render_email(
            org_name="Acme", inviter="admin@acme.test",
            url="https://bi.example.com/accept-invite?token=abc",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )

        assert "Acme" in subject
        assert "https://bi.example.com/accept-invite?token=abc" in text
        assert "https://bi.example.com/accept-invite?token=abc" in html_body

    def test_an_org_name_containing_markup_is_escaped(self) -> None:
        # The org name is a value an admin typed, and this string is rendered as
        # markup by every recipient's mail client.
        _, _, html_body = invite_svc._render_email(
            org_name="<script>alert(1)</script>", inviter=None,
            url="https://bi.example.com/accept-invite?token=abc",
            expires_at=datetime.now(UTC),
        )

        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    @pytest.mark.asyncio
    async def test_a_failed_send_is_reported_not_raised(self) -> None:
        # The invitation and its link are already valid; an admin told "not
        # sent" can copy the link instead.
        db = _session(_scalar_result("Acme"))

        with patch(
            "app.services.pipeline_notifications._send_email",
            new=AsyncMock(return_value=(False, "SMTP is not configured (set SMTP_HOST).")),
        ):
            sent, error = await invite_svc.send_invite_email(db, _invite())

        assert sent is False
        assert "SMTP" in (error or "")


# ---------------------------------------------------------------------------
# Redeeming
# ---------------------------------------------------------------------------


class TestPreviewInvite:
    @pytest.mark.asyncio
    async def test_an_unknown_token_is_a_404(self) -> None:
        db = _session(_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.preview_invite(db, "nope")

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_an_expired_token_describes_itself_rather_than_refusing(self) -> None:
        # The invitee needs to be told the link is stale, not shown an empty
        # form that fails on submit.
        db = _session(_scalar_result(_invite(expires_in_days=-1)), _scalar_result("Acme"))

        preview = await invite_svc.preview_invite(db, "tok-abc")

        assert preview.status == "expired"
        assert preview.org_name == "Acme"


class TestAcceptInvite:
    @pytest.mark.asyncio
    async def test_creates_the_account_the_invitation_names(self) -> None:
        db = _session(_scalar_result(_invite(role_id=4)), _scalar_result(None))

        with patch("app.services.invites.hash_password", return_value="hashed"):
            user = await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert user.email == "new@example.com"
        assert user.display_name == "Jane Smith"
        assert db.add.call_count == 2  # the user, and the role from the invitation

    @pytest.mark.asyncio
    async def test_the_address_comes_from_the_invitation_not_the_request(self) -> None:
        # The token proves the holder reached one mailbox; letting them name
        # another would make one invitation an account for anyone.
        db = _session(_scalar_result(_invite(email="invited@example.com")), _scalar_result(None))

        with patch("app.services.invites.hash_password", return_value="hashed"):
            user = await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert user.email == "invited@example.com"

    @pytest.mark.asyncio
    async def test_stamps_the_invitation_used(self) -> None:
        invite = _invite()
        db = _session(_scalar_result(invite), _scalar_result(None))

        with patch("app.services.invites.hash_password", return_value="hashed"):
            await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert invite.accepted_at is not None

    @pytest.mark.asyncio
    async def test_a_used_invitation_is_refused(self) -> None:
        db = _session(_scalar_result(_invite(accepted=True)))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_an_expired_invitation_is_refused_with_410(self) -> None:
        db = _session(_scalar_result(_invite(expires_in_days=-1)))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert exc.value.status_code == 410

    @pytest.mark.asyncio
    async def test_a_short_password_is_refused_before_the_token_is_read(self) -> None:
        db = _session()

        with pytest.raises(HTTPException) as exc:
            await invite_svc.accept_invite(db, "tok-abc", AcceptInviteRequest(password="short"))

        assert exc.value.status_code == 422
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_address_registered_since_the_invitation_is_refused(self) -> None:
        db = _session(_scalar_result(_invite()), _scalar_result(42))

        with pytest.raises(HTTPException) as exc:
            await invite_svc.accept_invite(
                db, "tok-abc", AcceptInviteRequest(password="a-long-enough-password")
            )

        assert exc.value.status_code == 409
