"""add safe API target fingerprints to failure patterns"""

import sqlalchemy as sa
from alembic import op

revision = "0009_api_target_fingerprints"
down_revision = "0008_tenant_private_negative_cases"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("failure_patterns", "global_failure_patterns"):
        op.add_column(table, sa.Column("api_target_fingerprint", sa.String(64), nullable=True))
        op.create_index(f"ix_{table}_api_target_fingerprint", table, ["api_target_fingerprint"])


def downgrade():
    for table in ("global_failure_patterns", "failure_patterns"):
        op.drop_index(f"ix_{table}_api_target_fingerprint", table_name=table)
        op.drop_column(table, "api_target_fingerprint")
