"""scope global evaluation evidence to a tenant"""

import sqlalchemy as sa
from alembic import op

revision = "0008_tenant_private_negative_cases"
down_revision = "0007_global_evaluations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "global_evaluation_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
    )
    # SQLite cannot add a foreign key constraint after table creation. PostgreSQL
    # receives the database constraint; application authorization covers both.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_global_evaluation_runs_tenant_id_tenants",
            "global_evaluation_runs",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_global_evaluation_runs_tenant_id", "global_evaluation_runs", ["tenant_id"])


def downgrade():
    op.drop_index("ix_global_evaluation_runs_tenant_id", table_name="global_evaluation_runs")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_global_evaluation_runs_tenant_id_tenants",
            "global_evaluation_runs",
            type_="foreignkey",
        )
    op.drop_column("global_evaluation_runs", "tenant_id")
