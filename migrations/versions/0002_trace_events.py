"""trace event storage"""

import sqlalchemy as sa
from alembic import op

revision = "0002_trace_events"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "agents",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])
    op.create_index("ix_agents_project_id", "agents", ["project_id"])
    op.create_table(
        "sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index("ix_sessions_project_id", "sessions", ["project_id"])
    op.create_table(
        "execution_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id", uuid, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("trace_id", sa.String(200), nullable=False),
        sa.Column("span_id", sa.String(200), nullable=False),
        sa.Column("parent_span_id", sa.String(200)),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("canonical_action", sa.String(100), nullable=False),
        sa.Column("native_tool_name", sa.String(200)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error_type", sa.String(100)),
        sa.Column("attributes", sa.JSON, nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id"),
    )
    for name, columns in (
        ("ix_execution_events_tenant_id", ["tenant_id"]),
        ("ix_execution_events_project_id", ["project_id"]),
        ("ix_execution_events_session_id", ["session_id"]),
        ("ix_execution_events_trace_id", ["tenant_id", "trace_id", "timestamp"]),
        ("ix_execution_events_timestamp", ["timestamp"]),
    ):
        op.create_index(name, "execution_events", columns)


def downgrade():
    op.drop_table("execution_events")
    op.drop_table("sessions")
    op.drop_table("agents")
