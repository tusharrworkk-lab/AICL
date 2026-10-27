"""evaluation definitions and strategy lifecycle"""

import sqlalchemy as sa
from alembic import op

revision = "0004_evaluation_learning"
down_revision = "0003_failure_intelligence"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "evaluation_definitions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "failure_pattern_id",
            uuid,
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("inputs", sa.JSON, nullable=False),
        sa.Column("preconditions", sa.JSON, nullable=False),
        sa.Column("expected_outcomes", sa.JSON, nullable=False),
        sa.Column("constraints", sa.JSON, nullable=False),
        sa.Column("pass_criteria", sa.JSON, nullable=False),
        sa.Column("evidence_requirements", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "failure_pattern_id", "version"),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "definition_id",
            uuid,
            sa.ForeignKey("evaluation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("passed", sa.Boolean),
        sa.Column("observed_actions", sa.JSON, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "strategy_candidates",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "failure_pattern_id",
            uuid,
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("applicability", sa.JSON, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "candidate_id",
            uuid,
            sa.ForeignKey("strategy_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("actions", sa.JSON, nullable=False),
        sa.Column("validation_status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("candidate_id", "version"),
    )
    op.create_table(
        "strategy_evidence",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "strategy_version_id",
            uuid,
            sa.ForeignKey("strategy_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_run_id",
            uuid,
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in (
        ("evaluation_definitions", ["tenant_id"]),
        ("evaluation_runs", ["tenant_id"]),
        ("strategy_candidates", ["tenant_id"]),
        ("strategy_versions", ["candidate_id"]),
        ("strategy_evidence", ["strategy_version_id"]),
    ):
        op.create_index(f"ix_{table}_{columns[0]}", table, columns)


def downgrade():
    for table in (
        "strategy_evidence",
        "strategy_versions",
        "strategy_candidates",
        "evaluation_runs",
        "evaluation_definitions",
    ):
        op.drop_table(table)
