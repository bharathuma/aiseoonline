"""Correlate private audit jobs with their initiating API request and trace.

Revision ID: 0005_audit_trace
Revises: 0004_audit_execution
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_audit_trace"
down_revision = "0004_audit_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_jobs", sa.Column("trace_parent", sa.String(55)))
    op.add_column("audit_jobs", sa.Column("request_id", sa.String(32)))


def downgrade() -> None:
    op.drop_column("audit_jobs", "request_id")
    op.drop_column("audit_jobs", "trace_parent")
