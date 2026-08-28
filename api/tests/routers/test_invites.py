"""Unit tests for the invitation endpoints, admin and public.

Two properties matter more than the rest and are pinned directly: the admin
always gets a copyable link back even when the email fails, and the accept
routes are reachable without a session while every issuing route is not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.auth import CurrentUser
from app.routers import admin as admin_router
from app.routers import invites as public_router
from app.schemas.invite import AcceptInviteRequest, InviteRequest


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _session(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=list(results) or None)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


def _invite(*, invite_id: int = 3, accepted: bool = False) -> MagicMock:
    now = datetime.now(UTC)
    invite = MagicMock()
    invite.id = invite_id
    invite.org_id = 1
    invite.email = "new@example.com"
    invite.token = "tok-abc"
    invite.first_name = None
    invite.last_name = None
    invite.role_id = None
    invite.expires_at = now + timedelta(days=7)
    invite.accepted_at = now if accepted else None
    invite.created_at = now
    return invite


class TestInviteUser:
    @pytest.mark.asyncio
    async def test_returns_a_copyable_link_and_reports_the_send(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = _session()

        with (
            patch.object(
                admin_router.invite_svc, "create_invite", new=AsyncMock(return_value=_invite())
            ),
            patch.object(
                admin_router.invite_svc, "role_name_for", new=AsyncMock(return_value=None)
            ),
            patch.object(
                admin_router.invite_svc,
                "send_invite_email",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch.object(admin_router.invite_svc.settings, "nextauth_url", "https://bi.test"),
        ):
            result = await admin_router.invite_user(
                InviteRequest(email="new@example.com"), mock_admin_user, db
            )

        assert result.invite_url == "https://bi.test/accept-invite?token=tok-abc"
        assert result.email_sent is True

    @pytest.mark.asyncio
    async def test_a_failed_send_still_returns_the_link(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # Without SMTP the link is the only way to invite anyone, so a send
        # failure must not become an error the admin sees instead of a link.
        db = _session()

        with (
            patch.object(
                admin_router.invite_svc, "create_invite", new=AsyncMock(return_value=_invite())
            ),
            patch.object(
                admin_router.invite_svc, "role_name_for", new=AsyncMock(return_value=None)
            ),
            patch.object(
                admin_router.invite_svc,
                "send_invite_email",
                new=AsyncMock(return_value=(False, "SMTP is not configured (set SMTP_HOST).")),
            ),
        ):
            result = await admin_router.invite_user(
                InviteRequest(email="new@example.com"), mock_admin_user, db
            )

        assert result.email_sent is False
        assert "SMTP" in (result.email_error or "")
        assert result.invite_url.endswith("?token=tok-abc")

    @pytest.mark.asyncio
    async def test_send_email_false_skips_delivery_entirely(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = _session()
        send = AsyncMock(return_value=(True, None))

        with (
            patch.object(
                admin_router.invite_svc, "create_invite", new=AsyncMock(return_value=_invite())
            ),
            patch.object(
                admin_router.invite_svc, "role_name_for", new=AsyncMock(return_value=None)
            ),
            patch.object(admin_router.invite_svc, "send_invite_email", new=send),
        ):
            result = await admin_router.invite_user(
                InviteRequest(email="new@example.com", send_email=False), mock_admin_user, db
            )

        send.assert_not_awaited()
        assert result.email_sent is None
        assert result.invite_url.endswith("?token=tok-abc")


class TestResendInvite:
    @pytest.mark.asyncio
    async def test_mints_a_new_token_and_mails_it(self, mock_admin_user: CurrentUser) -> None:
        db = _session()
        invite = _invite()
        refresh = AsyncMock(return_value=invite)

        with (
            patch.object(
                admin_router.invite_svc, "load_invite", new=AsyncMock(return_value=invite)
            ),
            patch.object(admin_router.invite_svc, "refresh_invite", new=refresh),
            patch.object(
                admin_router.invite_svc, "role_name_for", new=AsyncMock(return_value=None)
            ),
            patch.object(
                admin_router.invite_svc,
                "send_invite_email",
                new=AsyncMock(return_value=(True, None)),
            ),
        ):
            result = await admin_router.resend_invite(3, mock_admin_user, db)

        refresh.assert_awaited_once()
        assert result.email_sent is True

    @pytest.mark.asyncio
    async def test_an_accepted_invitation_cannot_be_resent(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = _session()

        with patch.object(
            admin_router.invite_svc,
            "load_invite",
            new=AsyncMock(return_value=_invite(accepted=True)),
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_router.resend_invite(3, mock_admin_user, db)

        assert exc.value.status_code == 409


class TestRevokeInvite:
    @pytest.mark.asyncio
    async def test_deletes_the_row_so_the_link_stops_working(
        self, mock_admin_user: CurrentUser
    ) -> None:
        db = _session()
        invite = _invite()

        with patch.object(
            admin_router.invite_svc, "load_invite", new=AsyncMock(return_value=invite)
        ):
            await admin_router.revoke_invite(3, mock_admin_user, db)

        db.delete.assert_awaited_once_with(invite)

    @pytest.mark.asyncio
    async def test_another_orgs_invitation_is_a_404(self, mock_admin_user: CurrentUser) -> None:
        db = _session(_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await admin_router.revoke_invite(3, mock_admin_user, db)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_an_accepted_invitation_cannot_be_revoked(
        self, mock_admin_user: CurrentUser
    ) -> None:
        # Revoking would delete the record of how an existing account came to be.
        db = _session()

        with patch.object(
            admin_router.invite_svc,
            "load_invite",
            new=AsyncMock(return_value=_invite(accepted=True)),
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_router.revoke_invite(3, mock_admin_user, db)

        assert exc.value.status_code == 409


class TestPublicRoutes:
    def test_issuing_is_admin_gated_and_redeeming_is_not(self) -> None:
        # The whole design rests on this split: the token is the only credential
        # the invitee has, and every route that mints one needs a session.
        admin_routes = [r for r in admin_router.router.routes if "invite" in r.path]
        assert admin_routes, "the admin invite routes disappeared"
        for route in admin_routes:
            calls = [d.call for d in route.dependant.dependencies]
            assert admin_router._admin_dep in calls, f"{route.path} is not admin-gated"

        for route in public_router.router.routes:
            modules = {getattr(d.call, "__module__", "") for d in route.dependant.dependencies}
            assert "app.middleware.auth" not in modules, f"{route.path} requires a session"

    @pytest.mark.asyncio
    async def test_accept_records_an_audit_entry_against_the_new_account(self) -> None:
        db = _session()
        user = MagicMock(id=11, org_id=1, email="new@example.com")
        recorded = AsyncMock()

        with (
            patch.object(
                public_router.invite_svc, "accept_invite", new=AsyncMock(return_value=user)
            ),
            patch.object(public_router, "audit_action", new=recorded),
        ):
            result = await public_router.accept_invite("tok-abc", AcceptInviteRequest(
                password="a-long-enough-password"
            ), db)

        assert "Sign in" in result.message
        assert recorded.await_args.kwargs["action"] == "invite.accepted"
        assert recorded.await_args.kwargs["user_id"] == 11
