"""context compiler audit records"""

import sqlalchemy as sa
from alembic import op

revision = "0005_context_compiler"
down_revision = "0004_evaluation_learning"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "context_requests",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("request_conditions", sa.JSON, nullable=False),
        sa.Column("result_summary", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_context_requests_tenant_id", "context_requests", ["tenant_id"])
    op.create_index("ix_context_requests_project_id", "context_requests", ["project_id"])


def downgrade():
    op.drop_table("context_requests")
