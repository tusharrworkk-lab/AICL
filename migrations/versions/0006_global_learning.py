"""de-identified global recurrence index"""

import sqlalchemy as sa
from alembic import op

revision = "0006_global_learning"
down_revision = "0005_context_compiler"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("global_learning_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    uuid = sa.Uuid()
    op.create_table(
        "global_failure_patterns",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("canonical_action", sa.String(100), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("native_tool_name", sa.String(200)),
        sa.Column("environment_fingerprint", sa.String(200)),
        sa.Column("recurrence_count", sa.Integer, nullable=False),
        sa.Column("source_tenant_count", sa.Integer, nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_global_failure_patterns_fingerprint", "global_failure_patterns", ["fingerprint"]
    )
    op.create_table(
        "global_failure_observations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "global_pattern_id",
            uuid,
            sa.ForeignKey("global_failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "failure_pattern_id",
            uuid,
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("global_pattern_id", "tenant_id", "failure_pattern_id"),
    )
    for name, column in (
        ("ix_global_failure_observations_global_pattern_id", "global_pattern_id"),
        ("ix_global_failure_observations_tenant_id", "tenant_id"),
        ("ix_global_failure_observations_failure_pattern_id", "failure_pattern_id"),
    ):
        op.create_index(name, "global_failure_observations", [column])


def downgrade():
    op.drop_table("global_failure_observations")
    op.drop_table("global_failure_patterns")
    op.drop_column("tenants", "global_learning_enabled")
