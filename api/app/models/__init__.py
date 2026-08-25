"""ORM model package.

Importing this module registers every table on the shared declarative `Base`, which
is what lets Alembic autogenerate see them. A new model file must be imported here
or its table will be silently absent from migrations.
"""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.auth_config import AuthProviderConfig, MfaSettings
from app.models.bi_connection import BiConnection
from app.models.change_ledger import ChangeLedgerEntry
from app.models.dashboard import (
    DashboardConfig,
    DashboardConfigVersion,
    DashboardFilter,
    DashboardPermission,
)
from app.models.data_dict import (
    DataDictionaryChangeLog,
    DataDictionaryEntry,
    DataDictionaryExclusion,
    DataDictionaryPermission,
)
from app.models.data_pipeline import DataPipelineConnection, DataPipelineConnectionPermission
from app.models.export import ExportJob, ExportSchedule
from app.models.favorite import UserFavorite
from app.models.feature_flag import FeatureFlag
from app.models.notification import NotificationPreference
from app.models.org_settings import OrgSettings
from app.models.page import CustomPage, CustomPagePermission, CustomPageVersion
from app.models.pipeline_notification import (
    NotificationCondition,
    NotificationDelivery,
    NotificationGroup,
    PipelineNotificationConfig,
)
from app.models.user import Org, Permission, Role, RolePermission, User, UserInvite, UserRole
from app.models.warehouse import WarehouseConnection, WarehouseConnectionPermission

__all__ = [
    "AuditLog",
    "AuthProviderConfig",
    "BiConnection",
    "ChangeLedgerEntry",
    "CustomPage",
    "CustomPagePermission",
    "CustomPageVersion",
    "DashboardConfig",
    "DashboardConfigVersion",
    "DashboardFilter",
    "DashboardPermission",
    "DataDictionaryChangeLog",
    "DataDictionaryEntry",
    "DataDictionaryExclusion",
    "DataDictionaryPermission",
    "DataPipelineConnection",
    "DataPipelineConnectionPermission",
    "ExportJob",
    "ExportSchedule",
    "FeatureFlag",
    "MfaSettings",
    "NotificationCondition",
    "NotificationDelivery",
    "NotificationGroup",
    "NotificationPreference",
    "Org",
    "OrgSettings",
    "Permission",
    "PipelineNotificationConfig",
    "Role",
    "RolePermission",
    "User",
    "UserFavorite",
    "UserInvite",
    "UserRole",
    "WarehouseConnection",
    "WarehouseConnectionPermission",
]
