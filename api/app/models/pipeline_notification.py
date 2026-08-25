"""Pipeline monitoring notification models.

A NotificationGroup is a reusable set of destinations (Slack/Teams/Google Chat
webhooks, email users, SMS users). A PipelineNotificationConfig attaches
monitoring settings to a data pipeline connection: whether to notify on
success/failure, the message templates, the poll frequency, which notification
groups to send to, and per-pipeline on/off overrides. A NotificationCondition
is a periodic health check on a connection (pipeline idle / data freshness)
that alerts on state transitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NotificationGroup(Base, TimestampMixin):
    """A named, reusable set of notification destinations for an org.

    ``channels`` shape (all keys optional):
        {
          "slack":  ["https://hooks.slack.com/…", …],   # webhook URLs
          "teams":  ["https://…webhook.office.com/…", …],
          "gchat":  ["https://chat.googleapis.com/…", …],
          "email":  [<user_id>, …],   # resolved to each user's email
          "sms":    [<user_id>, …],   # resolved to each user's phone_number
        }
    """

    __tablename__ = "notification_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PipelineNotificationConfig(Base, TimestampMixin):
    """Monitoring + notification settings for one data pipeline connection.

    Pipeline-level overrides live in ``pipeline_overrides`` as {name: bool};
    a pipeline absent from the map inherits the connection-level ``enabled``.
    Poller bookkeeping (``last_polled_at``, ``notified_run_ids``) prevents
    re-notifying for runs already seen.
    """

    __tablename__ = "pipeline_notification_configs"
    __table_args__ = (
        UniqueConstraint("pipeline_connection_id", name="uq_pipeline_notif_conn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    pipeline_connection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("data_pipeline_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_on_success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    success_message: Mapped[str] = mapped_column(
        Text, nullable=False,
        default="✅ Pipeline {pipeline} succeeded on {connection}.",
    )
    failure_message: Mapped[str] = mapped_column(
        Text, nullable=False,
        default="❌ Pipeline {pipeline} failed on {connection}: {message}",
    )
    # Poll cadence in minutes — clamped to [10, 1440] (10 min … 24 h) in the router.
    poll_frequency_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # Success and failure alerts route to independent notification groups.
    success_group_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    failure_group_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    # Per-pipeline overrides of the connection defaults, keyed by pipeline name.
    # Each value is a partial object; absent keys inherit the default:
    #   {name: {notify_on_success?, notify_on_failure?, success_message?, failure_message?}}
    pipeline_overrides: Mapped[dict[str, dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    # Suppress repeat alerts for the same (pipeline, kind) inside this window.
    # 0 disables throttling. Guards against a flapping pipeline spamming a channel.
    min_interval_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Quiet hours, as hours 0-23 in `quiet_hours_tz`. A window may wrap midnight
    # (start 22, end 6). NULL start or end disables it. Failures still alert
    # unless quiet_hours_include_failures is set — an outage usually outranks
    # the on-call schedule.
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_tz: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    quiet_hours_include_failures: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notified_run_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Throttle bookkeeping: {"<pipeline>|<kind>": "<iso timestamp>"} of the last
    # alert actually sent, used to enforce min_interval_minutes.
    last_alert_at: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)


class NotificationCondition(Base, TimestampMixin):
    """A condition check attached to a pipeline connection.

    Two condition types:
        pipeline_idle — triggers when the connection (or one named pipeline)
            has not started a run within ``threshold_minutes``.
        data_freshness — triggers when ``max(timestamp_column)`` of a warehouse
            table is older than ``threshold_minutes``. ``warehouse_connection_id``
            selects the warehouse to probe (NULL = the built-in marts warehouse).

    Alerts are state-transition based: one notification when the condition
    trips (``is_triggered`` False→True) and one on recovery (True→False, if
    ``notify_on_recovery``). ``last_observed_at`` records the newest run start /
    max timestamp seen by the last check.
    """

    __tablename__ = "notification_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    pipeline_connection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("data_pipeline_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # condition_type: pipeline_idle | data_freshness
    condition_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    threshold_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Check cadence in minutes — clamped to [10, 1440] in the router.
    check_frequency_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # pipeline_idle only: restrict to one pipeline name (None = any run counts).
    pipeline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # data_freshness only: table to probe. NULL connection = built-in marts.
    warehouse_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("warehouse_connections.id"), nullable=True
    )
    schema_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp_column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Delivery
    group_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    message_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notify_on_recovery: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Check state
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationDelivery(Base):
    """One recorded attempt to deliver a notification to a set of destinations.

    Without this, ``send_to_groups`` returned a per-destination result that every
    caller threw away, leaving "did my alert actually go out?" unanswerable. One
    row is written per send, with the per-destination outcome in ``details``.

    ``source`` values:
        run_success / run_failure — a pipeline run alert from the poller
        condition_trigger / condition_recovery — a NotificationCondition
            transition
        test — an operator-initiated test send

    ``details`` shape:
        [{"channel": "slack", "target": "https://…", "ok": true, "error": null}, …]

    ``pipeline_connection_id`` and ``condition_id`` are SET NULL on delete so the
    audit trail survives the config it came from.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        # The history view always filters by connection and orders by recency.
        Index(
            "ix_notif_deliveries_conn_created",
            "org_id",
            "pipeline_connection_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_connection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("data_pipeline_connections.id"),
        nullable=True,
    )
    condition_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("notification_conditions.id"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    group_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
