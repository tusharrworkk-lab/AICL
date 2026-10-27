"""foundation tables"""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "tenants",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_table(
        "projects",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])


def downgrade():
    for name in ("projects", "api_keys", "tenant_memberships", "users", "tenants"):
        op.drop_table(name)
