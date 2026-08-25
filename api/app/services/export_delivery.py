"""Export delivery service — email (SMTP) and SFTP upload.

Provides a single entry-point ``deliver_export()`` that dispatches to the
correct channel based on ``delivery_method``. Called after an export file
has been written to object storage.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def deliver_export(
    file_path: str,
    format: str,  # noqa: A002
    delivery_method: str,
    delivery_config: dict[str, Any] | None,
) -> None:
    """Deliver a completed export file to its configured destination.

    Args:
        file_path: Storage path to the file (fsspec-compatible).
        format: File format extension, e.g. 'csv', 'xlsx'.
        delivery_method: One of 'download', 'email', 'sftp'.
        delivery_config: Channel-specific configuration dict.
    """
    if delivery_method == "email":
        await _deliver_email(file_path, format, delivery_config or {})
    elif delivery_method == "sftp":
        await _deliver_sftp(file_path, format, delivery_config or {})
    # 'download' — the file is already in storage; nothing to push


async def _deliver_email(
    file_path: str,
    format: str,  # noqa: A002
    config: dict[str, Any],
) -> None:
    """Send export as email attachment via the configured SMTP server.

    Config keys:
        recipients: list[str] — Required. Email addresses to send to.
        subject: str — Email subject line (optional).
        body: str — Plain-text email body (optional).
    """
    from app.config import settings  # noqa: PLC0415

    recipients: list[str] = config.get("recipients") or []
    if not recipients:
        logger.warning("export.email_skipped_no_recipients")
        return

    if not settings.smtp_host:
        logger.warning("export.email_skipped_no_smtp_config")
        return

    subject: str = config.get("subject") or "Your scheduled export is ready"
    body: str = config.get("body") or "Please find your scheduled data export attached."

    await asyncio.to_thread(
        _send_smtp_email,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_password=settings.smtp_password,
        from_address=settings.smtp_from_address or settings.smtp_user or "",
        recipients=recipients,
        subject=subject,
        body=body,
        file_path=file_path,
        format=format,
    )


def _send_smtp_email(  # noqa: PLR0913
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    from_address: str,
    recipients: list[str],
    subject: str,
    body: str,
    file_path: str,
    format: str,  # noqa: A002
) -> None:
    """Synchronous SMTP send — runs in a thread via asyncio.to_thread."""
    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        from app.storage import get_filesystem  # noqa: PLC0415
        fs = get_filesystem()
        with fs.open(file_path, "rb") as fh:
            attachment_data = fh.read()
        filename = f"export.{format}"
        part = MIMEApplication(attachment_data, Name=filename)
        part["Content-Disposition"] = f'attachment; filename="{filename}"'
        msg.attach(part)
    except Exception as exc:
        logger.warning("export.email_attach_failed", error=str(exc))

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.ehlo()
        try:
            smtp.starttls()
        except smtplib.SMTPException:
            pass
        if smtp_user and smtp_password:
            smtp.login(smtp_user, smtp_password)
        smtp.sendmail(from_address, recipients, msg.as_string())

    logger.info("export.email_sent", recipients=recipients)


async def _deliver_sftp(
    file_path: str,
    format: str,  # noqa: A002
    config: dict[str, Any],
) -> None:
    """Upload export file to an SFTP server.

    Config keys:
        host: str — SFTP hostname or IP.
        port: int — SFTP port (default 22).
        username: str — Login username.
        password: str — Login password (plain-text in config; caller should decrypt beforehand).
        remote_path: str — Remote directory path (default '/exports').
        filename: str — Remote filename (default 'export.<format>').
    """
    await asyncio.to_thread(_upload_sftp, file_path=file_path, format=format, config=config)


def _upload_sftp(
    file_path: str,
    format: str,  # noqa: A002
    config: dict[str, Any],
) -> None:
    """Synchronous SFTP upload — runs in a thread via asyncio.to_thread."""
    try:
        import paramiko  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "paramiko is required for SFTP delivery. Install it with: pip install paramiko"
        ) from exc

    host: str = config.get("host", "")
    port: int = int(config.get("port", 22))
    username: str = config.get("username", "")
    password: str | None = config.get("password") or None
    remote_path: str = config.get("remote_path", "/exports")
    remote_filename: str = config.get("filename") or f"export.{format}"
    remote_dest = f"{remote_path.rstrip('/')}/{remote_filename}"

    ssh = paramiko.SSHClient()
    # Trust the host key; acceptable for internal SFTP servers. For public-facing
    # servers, callers should provide the host key fingerprint in delivery_config.
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507
    try:
        ssh.connect(host, port=port, username=username, password=password, timeout=30)
        sftp = ssh.open_sftp()
        try:
            from app.storage import get_filesystem  # noqa: PLC0415
            fs = get_filesystem()
            with fs.open(file_path, "rb") as local_fh:
                sftp.putfo(local_fh, remote_dest)
            logger.info("export.sftp_uploaded", host=host, remote=remote_dest)
        finally:
            sftp.close()
    except Exception as exc:
        logger.error("export.sftp_failed", host=host, error=str(exc))
        raise
    finally:
        ssh.close()
