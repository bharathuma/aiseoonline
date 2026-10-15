"""Account sessions and domain verification state.

Revision ID: 0006_account_security
Revises: 0005_audit_trace
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_account_security"
down_revision = "0005_audit_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255)))
    op.add_column("projects", sa.Column("verification_token_hash", sa.String(64)))
    op.add_column("projects", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_column("projects", "verified_at")
    op.drop_column("projects", "verification_token_hash")
    op.drop_column("users", "password_hash")
