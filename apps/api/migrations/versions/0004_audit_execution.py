"""Durable private audit execution and structured report evidence.

Revision ID: 0004_audit_execution
Revises: 0003_rag_fulltext
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_audit_execution"
down_revision = "0003_rag_fulltext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_jobs", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.add_column("audit_jobs", sa.Column("requested_url", sa.Text(), nullable=True))
    op.add_column("audit_jobs", sa.Column("idempotency_key", sa.String(96), nullable=True))
    op.add_column("audit_jobs", sa.Column("request_data", sa.JSON(), nullable=True))
    op.add_column("audit_jobs", sa.Column("report_data", sa.JSON(), nullable=True))
    op.add_column(
        "audit_jobs",
        sa.Column("progress_step", sa.String(32), nullable=False, server_default="queued"),
    )
    op.add_column(
        "audit_jobs",
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("audit_jobs", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("audit_jobs", sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.add_column("audit_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "audit_jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_audit_jobs_owner",
        "audit_jobs",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_audit_project_idempotency", "audit_jobs", ["project_id", "idempotency_key"]
    )
    op.create_index("ix_audit_jobs_leases", "audit_jobs", ["status", "lease_expires_at"])
    op.create_check_constraint(
        "ck_audit_progress_percent", "audit_jobs", "progress_percent BETWEEN 0 AND 100"
    )
    op.add_column("seo_findings", sa.Column("finding_key", sa.String(100)))
    op.add_column("seo_findings", sa.Column("affected_url", sa.Text()))
    op.add_column("seo_findings", sa.Column("correction", sa.Text()))
    op.add_column("seo_findings", sa.Column("evidence_ref", sa.String(120)))
    op.create_unique_constraint(
        "uq_audit_finding_key", "seo_findings", ["audit_job_id", "finding_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_audit_finding_key", "seo_findings", type_="unique")
    for name in ("evidence_ref", "correction", "affected_url", "finding_key"):
        op.drop_column("seo_findings", name)
    op.drop_constraint("ck_audit_progress_percent", "audit_jobs", type_="check")
    op.drop_index("ix_audit_jobs_leases", table_name="audit_jobs")
    op.drop_constraint("uq_audit_project_idempotency", "audit_jobs", type_="unique")
    op.drop_constraint("fk_audit_jobs_owner", "audit_jobs", type_="foreignkey")
    for name in (
        "cancel_requested",
        "lease_expires_at",
        "finished_at",
        "started_at",
        "attempts",
        "progress_percent",
        "progress_step",
        "report_data",
        "request_data",
        "idempotency_key",
        "requested_url",
        "owner_id",
    ):
        op.drop_column("audit_jobs", name)
