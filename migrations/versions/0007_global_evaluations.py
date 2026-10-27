"""global evaluation and judge records"""

import sqlalchemy as sa
from alembic import op

revision = "0007_global_evaluations"
down_revision = "0006_global_learning"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "global_evaluation_definitions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "global_pattern_id",
            uuid,
            sa.ForeignKey("global_failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("preconditions", sa.JSON, nullable=False),
        sa.Column("pass_criteria", sa.JSON, nullable=False),
        sa.Column("evidence_requirements", sa.JSON, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("global_pattern_id", "version"),
    )
    op.create_table(
        "global_evaluation_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "definition_id",
            uuid,
            sa.ForeignKey("global_evaluation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("judge_provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("observed_actions", sa.JSON, nullable=False),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("blockers", sa.JSON, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "global_strategy_candidates",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "global_pattern_id",
            uuid,
            sa.ForeignKey("global_failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_definition_id",
            uuid,
            sa.ForeignKey("global_evaluation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("actions", sa.JSON, nullable=False),
        sa.Column("applicability", sa.JSON, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("validation_status", sa.String(30), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, column in (
        ("global_evaluation_definitions", "global_pattern_id"),
        ("global_evaluation_runs", "definition_id"),
        ("global_strategy_candidates", "global_pattern_id"),
        ("global_strategy_candidates", "evaluation_definition_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("global_strategy_candidates")
    op.drop_table("global_evaluation_runs")
    op.drop_table("global_evaluation_definitions")
