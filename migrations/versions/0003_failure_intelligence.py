"""failure patterns and occurrences"""

import sqlalchemy as sa
from alembic import op

revision = "0003_failure_intelligence"
down_revision = "0002_trace_events"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "failure_patterns",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("canonical_action", sa.String(100), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("native_tool_name", sa.String(200)),
        sa.Column("environment_fingerprint", sa.String(200)),
        sa.Column("occurrence_count", sa.Integer, nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "project_id", "fingerprint"),
    )
    op.create_index("ix_failure_patterns_tenant_id", "failure_patterns", ["tenant_id"])
    op.create_index("ix_failure_patterns_project_id", "failure_patterns", ["project_id"])
    op.create_index("ix_failure_patterns_tenant", "failure_patterns", ["tenant_id", "project_id"])
    op.create_table(
        "failure_occurrences",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "pattern_id",
            uuid,
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            uuid,
            sa.ForeignKey("execution_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id", uuid, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_error", sa.String(200), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id"),
    )
    for name, columns in (
        ("ix_failure_occurrences_tenant_id", ["tenant_id"]),
        ("ix_failure_occurrences_project_id", ["project_id"]),
        ("ix_failure_occurrences_pattern_id", ["pattern_id"]),
        ("ix_failure_occurrences_event_id", ["event_id"]),
        ("ix_failure_occurrences_session_id", ["session_id"]),
        ("ix_failure_occurrences_observed_at", ["observed_at"]),
    ):
        op.create_index(name, "failure_occurrences", columns)


def downgrade():
    op.drop_table("failure_occurrences")
    op.drop_table("failure_patterns")
