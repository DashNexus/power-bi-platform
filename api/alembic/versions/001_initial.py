"""Create the whole schema and seed the default organisation.

This build ships one migration rather than a chain: it is a fresh fork with no
deployed database to upgrade, and a single file is easier to read than sixty-odd
increments describing history that never happened here. Later changes get their
own revision as usual.

Seeds:
- Default organisation (slug='default')
- Five system roles: superadmin, admin, manager, analyst, viewer
- The permission vocabulary, and the role/permission matrix
- Default admin user (admin@example.com / admin123 — change after first login)
- Feature flags, all enabled
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

# The permission vocabulary. A key that no route references enforces nothing —
# every one below is checked by a `require_permission` / `user_has_permission`
# call in `app/routers` or `app/services`.
#
# There are deliberately no `admin.*` keys: each would let its holder become a
# full admin (assign roles, edit role permissions, register an identity
# provider), so they are an escalation path rather than a delegation.
# `require_role("admin")` gates those surfaces instead.
PERMISSIONS: list[tuple[str, str, str]] = [
    ("dashboards.view", "View dashboards shared with you", "Dashboards"),
    ("dashboards.manage", "Create, edit, and delete dashboards", "Dashboards"),
    ("pages.view", "View custom pages", "Pages"),
    ("pages.manage", "Create, edit, and delete custom pages", "Pages"),
    ("data_dictionary.view", "View the data dictionary", "Data Dictionary"),
    ("data_dictionary.manage", "Edit data dictionary entries", "Data Dictionary"),
    ("warehouses.view", "View warehouse connections", "Warehouses"),
    ("warehouses.manage", "Create, edit, and delete warehouse connections", "Warehouses"),
    ("bi_connections.view", "View BI connections", "BI Connections"),
    ("bi_connections.manage", "Create, edit, and delete BI connections", "BI Connections"),
    ("pipelines.view", "View pipeline connections and their runs", "Pipelines"),
    ("pipelines.manage", "Create, edit, and delete pipeline connections", "Pipelines"),
    ("exports.view", "View export jobs and schedules", "Exports"),
    ("exports.create", "Create exports and schedules", "Exports"),
    ("changes.view", "View the organisation-wide change history", "Changes"),
    ("audit.view", "View the audit log", "Audit"),
    ("audit.manage", "Set audit retention and purge old entries", "Audit"),
]

# admin and superadmin get every key (None below), so a permission added later is
# theirs without another migration — and an org can never lock itself out of its
# own console. viewer/analyst/manager are explicit.
_VIEWER = ["dashboards.view", "pages.view"]
_ANALYST = [
    *_VIEWER,
    "data_dictionary.view",
    "warehouses.view",
    "bi_connections.view",
    "pipelines.view",
    "exports.view",
    "exports.create",
]
_MANAGER = [
    *_ANALYST,
    "dashboards.manage",
    "pages.manage",
    "data_dictionary.manage",
    "warehouses.manage",
    "bi_connections.manage",
    "pipelines.manage",
    "changes.view",
    "audit.view",
]

ROLE_GRANTS: dict[str, list[str] | None] = {
    "viewer": _VIEWER,
    "analyst": _ANALYST,
    "manager": _MANAGER,
    "admin": None,
    "superadmin": None,
}

SYSTEM_ROLES: list[tuple[str, str]] = [
    ("superadmin", "Super administrator with full access"),
    ("admin", "Administrator with access to all admin features"),
    ("manager", "Curates connections, dashboards, pages, and the data dictionary"),
    ("analyst", "Reads dashboards, pages, the data dictionary, and creates exports"),
    ("viewer", "Read-only access to dashboards and pages"),
]

# Every flag this build knows about (see app/config.py::FEATURE_ENV_VARS), on by
# default. An org turns off what it does not use from /admin/features.
DEFAULT_FEATURE_FLAGS: list[str] = [
    "dashboards",
    "custom_pages",
    "exports",
    "governance",
    "pipelines",
    "embed.powerbi",
    "embed.page",
    "pipelines.adf",
]

def upgrade() -> None:
    op.create_table('orgs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('category', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('auth_provider_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('client_id', sa.String(length=255), nullable=True),
    sa.Column('client_secret_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'provider', name='uq_auth_provider_org_provider')
    )
    op.create_table('bi_connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('secret_encrypted', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('data_pipeline_connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('secret_encrypted', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mfa_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('totp_enabled', sa.Boolean(), nullable=False),
    sa.Column('totp_required', sa.Boolean(), nullable=False),
    sa.Column('email_otp_enabled', sa.Boolean(), nullable=False),
    sa.Column('grace_period_days', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id')
    )
    op.create_table('notification_groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('channels', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('org_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('app_name', sa.String(length=255), nullable=False),
    sa.Column('logo_url', sa.String(length=1024), nullable=True),
    sa.Column('audit_retention_days', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id')
    )
    op.create_table('roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_roles_org_name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('first_name', sa.String(length=255), nullable=True),
    sa.Column('last_name', sa.String(length=255), nullable=True),
    sa.Column('department', sa.String(length=255), nullable=True),
    sa.Column('job_title', sa.String(length=255), nullable=True),
    sa.Column('avatar_url', sa.String(length=1024), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('phone_number', sa.String(length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('totp_secret_encrypted', sa.String(length=512), nullable=True),
    sa.Column('totp_enabled', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('warehouse_connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('db_type', sa.String(length=32), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('database_name', sa.String(length=255), nullable=True),
    sa.Column('username', sa.String(length=255), nullable=True),
    sa.Column('password_encrypted', sa.Text(), nullable=True),
    sa.Column('schemas', sa.JSON(), nullable=False),
    sa.Column('extra_config', sa.JSON(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.Integer(), nullable=True),
    sa.Column('resource_name', sa.String(length=255), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('change_ledger',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('correlation_id', sa.String(length=36), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('before', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('after', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('resource_name', sa.String(length=255), nullable=True),
    sa.Column('revert_of_id', sa.Integer(), nullable=True),
    sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reverted_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("action IN ('create', 'update', 'delete')", name='ck_change_ledger_action'),
    sa.CheckConstraint("source IN ('user', 'ai', 'system')", name='ck_change_ledger_source'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revert_of_id'], ['change_ledger.id'], ),
    sa.ForeignKeyConstraint(['reverted_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_change_ledger_correlation', 'change_ledger', ['correlation_id'], unique=False)
    op.create_index('ix_change_ledger_org_created', 'change_ledger', ['org_id', 'created_at'], unique=False)
    op.create_index('ix_change_ledger_org_source', 'change_ledger', ['org_id', 'source'], unique=False)
    op.create_index('ix_change_ledger_resource', 'change_ledger', ['org_id', 'resource_type', 'resource_id'], unique=False)
    op.create_table('custom_pages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('required_role', sa.String(length=32), nullable=False),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('is_home_page', sa.Boolean(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'slug', name='uq_custom_pages_org_slug')
    )
    op.create_table('dashboard_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('embed_type', sa.String(length=32), nullable=False),
    sa.Column('bi_connection_id', sa.Integer(), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('required_role', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['bi_connection_id'], ['bi_connections.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'slug', name='uq_dashboard_configs_org_slug')
    )
    op.create_table('data_dictionary_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=True),
    sa.Column('schema_name', sa.String(length=128), nullable=False),
    sa.Column('table_name', sa.String(length=128), nullable=False),
    sa.Column('column_name', sa.String(length=128), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('data_type', sa.String(length=128), nullable=True),
    sa.Column('is_pk', sa.Boolean(), nullable=False),
    sa.Column('fk_schema', sa.String(length=128), nullable=True),
    sa.Column('fk_table', sa.String(length=128), nullable=True),
    sa.Column('fk_column', sa.String(length=128), nullable=True),
    sa.Column('relationship_type', sa.String(length=32), nullable=True),
    sa.Column('is_pii', sa.Boolean(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('ai_generated', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'warehouse_connection_id', 'schema_name', 'table_name', 'column_name', name='uq_data_dict_entry')
    )
    op.create_table('data_dictionary_exclusions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=False),
    sa.Column('schema_name', sa.String(length=128), nullable=False),
    sa.Column('table_name', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'warehouse_connection_id', 'schema_name', 'table_name', name='uq_dd_exclusion')
    )
    op.create_table('data_dictionary_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.Column('can_edit', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('data_pipeline_connection_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('pipeline_connection_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['pipeline_connection_id'], ['data_pipeline_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('export_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=32), nullable=False),
    sa.Column('query_params', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('file_path', sa.String(length=1024), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('delivery_method', sa.String(length=32), server_default='download', nullable=False),
    sa.Column('delivery_config', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('export_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('format', sa.String(length=32), nullable=False),
    sa.Column('query_params', sa.JSON(), nullable=False),
    sa.Column('cron_expression', sa.String(length=128), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivery_method', sa.String(length=32), server_default='download', nullable=False),
    sa.Column('delivery_config', sa.JSON(), nullable=True),
    sa.Column('sql_query', sa.Text(), nullable=True),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('feature_flags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('feature_key', sa.String(length=128), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'feature_key', name='uq_feature_flags_org_key')
    )
    op.create_table('notification_conditions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('pipeline_connection_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('condition_type', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('threshold_minutes', sa.Integer(), nullable=False),
    sa.Column('check_frequency_minutes', sa.Integer(), nullable=False),
    sa.Column('pipeline_name', sa.String(length=255), nullable=True),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=True),
    sa.Column('schema_name', sa.String(length=128), nullable=True),
    sa.Column('table_name', sa.String(length=128), nullable=True),
    sa.Column('timestamp_column', sa.String(length=128), nullable=True),
    sa.Column('group_ids', sa.JSON(), nullable=False),
    sa.Column('message_template', sa.Text(), nullable=False),
    sa.Column('notify_on_recovery', sa.Boolean(), nullable=False),
    sa.Column('is_triggered', sa.Boolean(), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['pipeline_connection_id'], ['data_pipeline_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('notification_preferences',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('event_type', sa.String(length=128), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'channel', 'event_type', name='uq_notification_prefs')
    )
    op.create_table('pipeline_notification_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('pipeline_connection_id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('notify_on_success', sa.Boolean(), nullable=False),
    sa.Column('notify_on_failure', sa.Boolean(), nullable=False),
    sa.Column('success_message', sa.Text(), nullable=False),
    sa.Column('failure_message', sa.Text(), nullable=False),
    sa.Column('poll_frequency_minutes', sa.Integer(), nullable=False),
    sa.Column('success_group_ids', sa.JSON(), nullable=False),
    sa.Column('failure_group_ids', sa.JSON(), nullable=False),
    sa.Column('pipeline_overrides', sa.JSON(), nullable=False),
    sa.Column('min_interval_minutes', sa.Integer(), nullable=False),
    sa.Column('quiet_hours_start', sa.Integer(), nullable=True),
    sa.Column('quiet_hours_end', sa.Integer(), nullable=True),
    sa.Column('quiet_hours_tz', sa.String(length=64), nullable=False),
    sa.Column('quiet_hours_include_failures', sa.Boolean(), nullable=False),
    sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notified_run_ids', sa.JSON(), nullable=False),
    sa.Column('last_alert_at', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['pipeline_connection_id'], ['data_pipeline_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pipeline_connection_id', name='uq_pipeline_notif_conn')
    )
    op.create_table('role_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('permission_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permissions')
    )
    op.create_table('user_favorites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'resource_type', 'resource_id', name='uq_user_favorites')
    )
    op.create_table('user_invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('token', sa.String(length=255), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    op.create_table('user_roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'role_id', name='uq_user_roles')
    )
    op.create_table('warehouse_connection_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['warehouse_connection_id'], ['warehouse_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('custom_page_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('page_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['page_id'], ['custom_pages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('custom_page_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('page_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['page_id'], ['custom_pages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('dashboard_config_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dashboard_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('embed_type', sa.String(length=32), nullable=False),
    sa.Column('bi_connection_id', sa.Integer(), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('required_role', sa.String(length=32), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['bi_connection_id'], ['bi_connections.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['dashboard_id'], ['dashboard_configs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('dashboard_filters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dashboard_id', sa.Integer(), nullable=False),
    sa.Column('filter_key', sa.String(length=255), nullable=False),
    sa.Column('filter_label', sa.String(length=255), nullable=False),
    sa.Column('filter_type', sa.String(length=32), nullable=False),
    sa.Column('default_value', sa.String(length=255), nullable=True),
    sa.Column('user_attribute', sa.String(length=255), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['dashboard_id'], ['dashboard_configs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('dashboard_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dashboard_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dashboard_id'], ['dashboard_configs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('data_dictionary_changelog',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('entry_id', sa.Integer(), nullable=True),
    sa.Column('warehouse_connection_id', sa.Integer(), nullable=True),
    sa.Column('schema_name', sa.String(length=128), nullable=False),
    sa.Column('table_name', sa.String(length=128), nullable=False),
    sa.Column('column_name', sa.String(length=128), nullable=True),
    sa.Column('field_name', sa.String(length=128), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('changed_by_user_id', sa.Integer(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['entry_id'], ['data_dictionary_entries.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('notification_deliveries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('pipeline_connection_id', sa.Integer(), nullable=True),
    sa.Column('condition_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('pipeline_name', sa.String(length=255), nullable=True),
    sa.Column('run_id', sa.String(length=512), nullable=True),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('group_ids', sa.JSON(), nullable=False),
    sa.Column('sent_count', sa.Integer(), nullable=False),
    sa.Column('failed_count', sa.Integer(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['condition_id'], ['notification_conditions.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pipeline_connection_id'], ['data_pipeline_connections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notif_deliveries_conn_created', 'notification_deliveries', ['org_id', 'pipeline_connection_id', 'created_at'], unique=False)
    # ### end Alembic commands ###

    # Indexes on the columns list queries filter and order by. The org_id ones
    # matter because every tenant-scoped read carries `WHERE org_id = :org_id`;
    # the timestamp ones back the audit feed and the delivery-history prune,
    # which are ordered newest-first and swept by age.
    op.create_index('ix_audit_logs_org_id', 'audit_logs', ['org_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_dashboard_configs_org_id', 'dashboard_configs', ['org_id'])
    op.create_index('ix_custom_pages_org_id', 'custom_pages', ['org_id'])
    op.create_index('ix_data_dictionary_entries_org_id', 'data_dictionary_entries', ['org_id'])
    op.create_index('ix_export_jobs_org_id', 'export_jobs', ['org_id'])
    op.create_index('ix_feature_flags_org_id', 'feature_flags', ['org_id'])
    op.create_index('ix_notification_deliveries_created_at', 'notification_deliveries', ['created_at'])
    op.create_index('ix_user_roles_user_id', 'user_roles', ['user_id'])
    op.create_index('ix_users_org_id', 'users', ['org_id'])


    _seed(op.get_bind())


def _seed(conn: sa.engine.Connection) -> None:
    """Create the default org, its roles, permissions, admin user, and flags.

    Written with Core constructs and explicit SELECT-then-INSERT rather than raw
    SQL: ``RETURNING``, ``ON CONFLICT``, and ``NOW()`` are PostgreSQL spellings,
    and this migration also has to run against Azure SQL. The read-before-write
    also makes the whole function idempotent, so re-running against a partially
    seeded database is safe.
    """
    # A random salt per install, so two deployments never share a hash.
    try:
        import bcrypt  # noqa: PLC0415

        pw_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
    except ImportError:
        # Pre-computed bcrypt hash of "admin123" (cost 12).
        pw_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj3jp/X.kSe6"

    now = datetime.now(UTC)
    meta = sa.MetaData()

    def table(name: str, *columns: sa.Column) -> sa.Table:
        return sa.Table(name, meta, *columns)

    orgs = table(
        "orgs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("slug", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    org_settings = table(
        "org_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer),
        sa.Column("app_name", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    permissions = table(
        "permissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(255)),
        sa.Column("description", sa.String(1000)),
        sa.Column("category", sa.String(255)),
    )
    roles = table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer),
        sa.Column("name", sa.String(255)),
        sa.Column("description", sa.String(1000)),
        sa.Column("is_system", sa.Boolean),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    role_permissions = table(
        "role_permissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("role_id", sa.Integer),
        sa.Column("permission_id", sa.Integer),
    )
    users = table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer),
        sa.Column("email", sa.String(255)),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean),
        sa.Column("totp_enabled", sa.Boolean),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    user_roles = table(
        "user_roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("role_id", sa.Integer),
    )
    feature_flags = table(
        "feature_flags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer),
        sa.Column("feature_key", sa.String(128)),
        sa.Column("enabled", sa.Boolean),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    def insert_returning_id(tbl: sa.Table, **values: object) -> int:
        """Insert one row and return its primary key on either dialect.

        ``inserted_primary_key`` is what both the PostgreSQL (RETURNING) and the
        SQL Server (OUTPUT / SCOPE_IDENTITY) drivers populate, so asking
        SQLAlchemy beats writing either spelling by hand.
        """
        return int(conn.execute(sa.insert(tbl).values(**values)).inserted_primary_key[0])

    # ── Organisation ─────────────────────────────────────────────────────────
    org_id = conn.execute(sa.select(orgs.c.id).where(orgs.c.slug == "default")).scalar()
    if org_id is None:
        org_id = insert_returning_id(
            orgs, name="Default", slug="default", created_at=now, updated_at=now
        )

    has_settings = conn.execute(
        sa.select(org_settings.c.id).where(org_settings.c.org_id == org_id)
    ).scalar()
    if has_settings is None:
        conn.execute(
            sa.insert(org_settings).values(
                org_id=org_id, app_name="Power BI Platform", updated_at=now
            )
        )

    # ── Permissions ──────────────────────────────────────────────────────────
    existing_keys = {
        row[0] for row in conn.execute(sa.select(permissions.c.key)).fetchall()
    }
    new_rows = [
        {"key": key, "description": description, "category": category}
        for key, description, category in PERMISSIONS
        if key not in existing_keys
    ]
    if new_rows:
        conn.execute(sa.insert(permissions), new_rows)
    perm_id_by_key = {
        row[1]: row[0]
        for row in conn.execute(sa.select(permissions.c.id, permissions.c.key)).fetchall()
    }

    # ── System roles and their grants ────────────────────────────────────────
    role_ids: dict[str, int] = {}
    for name, description in SYSTEM_ROLES:
        role_id = conn.execute(
            sa.select(roles.c.id).where(roles.c.org_id == org_id, roles.c.name == name)
        ).scalar()
        if role_id is None:
            role_id = insert_returning_id(
                roles,
                org_id=org_id,
                name=name,
                description=description,
                is_system=True,
                created_at=now,
                updated_at=now,
            )
        role_ids[name] = role_id

    granted_pairs = {
        (row[0], row[1])
        for row in conn.execute(
            sa.select(role_permissions.c.role_id, role_permissions.c.permission_id)
        ).fetchall()
    }
    pending = [
        {"role_id": role_ids[role_name], "permission_id": perm_id}
        for role_name, keys in ROLE_GRANTS.items()
        for perm_id in (
            list(perm_id_by_key.values())
            if keys is None
            else [perm_id_by_key[k] for k in keys if k in perm_id_by_key]
        )
        if (role_ids[role_name], perm_id) not in granted_pairs
    ]
    if pending:
        conn.execute(sa.insert(role_permissions), pending)

    # ── Default admin user ───────────────────────────────────────────────────
    user_id = conn.execute(
        sa.select(users.c.id).where(users.c.email == "admin@example.com")
    ).scalar()
    if user_id is None:
        user_id = insert_returning_id(
            users,
            org_id=org_id,
            email="admin@example.com",
            hashed_password=pw_hash,
            display_name="Admin",
            is_active=True,
            totp_enabled=False,
            created_at=now,
            updated_at=now,
        )
    else:
        conn.execute(sa.update(users).where(users.c.id == user_id).values(org_id=org_id))

    superadmin_id = role_ids["superadmin"]
    has_role = conn.execute(
        sa.select(user_roles.c.id).where(
            user_roles.c.user_id == user_id, user_roles.c.role_id == superadmin_id
        )
    ).scalar()
    if has_role is None:
        conn.execute(sa.insert(user_roles).values(user_id=user_id, role_id=superadmin_id))

    # ── Feature flags ────────────────────────────────────────────────────────
    existing_flags = {
        row[0]
        for row in conn.execute(
            sa.select(feature_flags.c.feature_key).where(feature_flags.c.org_id == org_id)
        ).fetchall()
    }
    pending_flags = [
        {"org_id": org_id, "feature_key": key, "enabled": True, "updated_at": now}
        for key in DEFAULT_FEATURE_FLAGS
        if key not in existing_flags
    ]
    if pending_flags:
        conn.execute(sa.insert(feature_flags), pending_flags)


def downgrade() -> None:
    op.drop_index('ix_users_org_id', table_name='users')
    op.drop_index('ix_user_roles_user_id', table_name='user_roles')
    op.drop_index('ix_notification_deliveries_created_at', table_name='notification_deliveries')
    op.drop_index('ix_feature_flags_org_id', table_name='feature_flags')
    op.drop_index('ix_export_jobs_org_id', table_name='export_jobs')
    op.drop_index('ix_data_dictionary_entries_org_id', table_name='data_dictionary_entries')
    op.drop_index('ix_custom_pages_org_id', table_name='custom_pages')
    op.drop_index('ix_dashboard_configs_org_id', table_name='dashboard_configs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_org_id', table_name='audit_logs')
    op.drop_table('notification_deliveries')
    op.drop_table('data_dictionary_changelog')
    op.drop_table('dashboard_permissions')
    op.drop_table('dashboard_filters')
    op.drop_table('dashboard_config_versions')
    op.drop_table('custom_page_versions')
    op.drop_table('custom_page_permissions')
    op.drop_table('warehouse_connection_permissions')
    op.drop_table('user_roles')
    op.drop_table('user_invites')
    op.drop_table('user_favorites')
    op.drop_table('role_permissions')
    op.drop_table('pipeline_notification_configs')
    op.drop_table('notification_preferences')
    op.drop_table('notification_conditions')
    op.drop_table('feature_flags')
    op.drop_table('export_schedules')
    op.drop_table('export_jobs')
    op.drop_table('data_pipeline_connection_permissions')
    op.drop_table('data_dictionary_permissions')
    op.drop_table('data_dictionary_exclusions')
    op.drop_table('data_dictionary_entries')
    op.drop_table('dashboard_configs')
    op.drop_table('custom_pages')
    op.drop_table('change_ledger')
    op.drop_table('audit_logs')
    op.drop_table('warehouse_connections')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('org_settings')
    op.drop_table('notification_groups')
    op.drop_table('mfa_settings')
    op.drop_table('data_pipeline_connections')
    op.drop_table('bi_connections')
    op.drop_table('auth_provider_configs')
    op.drop_table('permissions')
    op.drop_table('orgs')
