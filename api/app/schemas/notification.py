"""Schemas for notification preferences."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class NotificationPrefRequest(BaseModel):
    """Request body for updating a notification preference.

    Attributes:
        channel: Notification channel - 'email', 'slack', 'teams', 'gchat', 'sms'.
        event_type: Event type to subscribe to (e.g. 'pipeline_failure', 'export_ready').
        enabled: Whether notifications are enabled for this combination.
        config: Channel-specific configuration (e.g. Slack channel name for email).
    """

    channel: str
    event_type: str
    enabled: bool = True
    config: dict[str, Any] | None = None


class NotificationPrefResponse(BaseModel):
    """Stored notification preference.

    Attributes:
        id: Database primary key.
        channel: Notification channel.
        event_type: Event type.
        enabled: Whether enabled.
        config: Channel-specific configuration.
    """

    id: int
    channel: str
    event_type: str
    enabled: bool
    config: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class NotificationEventResponse(BaseModel):
    """Metadata about a notification event that was sent.

    Attributes:
        id: Database primary key.
        event_type: Type of event that triggered the notification.
        channel: Channel the notification was sent to.
        recipient: Recipient identifier (email address, Slack channel, etc.).
        status: Delivery status - 'sent', 'failed', 'pending'.
        sent_at: When the notification was sent.
        error_message: Error description if delivery failed.
    """

    id: int
    event_type: str
    channel: str
    recipient: str
    status: str
    sent_at: str
    error_message: str | None = None

    model_config = {"from_attributes": True}


class NotificationChannelConfigRequest(BaseModel):
    """Request body for configuring a notification channel.

    Attributes:
        channel: Channel type - 'email', 'slack', 'teams', 'gchat', 'sms'.
        config: Channel-specific configuration settings.
    """

    channel: str
    config: dict[str, Any]
