"""Add private RAG document classification and PostgreSQL full-text indexing.

Revision ID: 0003_rag_fulltext
Revises: 0002_rag_vectors
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_rag_fulltext"
down_revision = "0002_rag_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("document_type", sa.String(24), nullable=False, server_default="web_page"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("access_scope", sa.String(24), nullable=False, server_default="owner_only"),
    )
    op.create_check_constraint(
        "ck_rag_document_type",
        "rag_documents",
        "document_type IN ('web_page', 'guide', 'reference')",
    )
    op.create_check_constraint(
        "ck_rag_document_access",
        "rag_documents",
        "access_scope = 'owner_only'",
    )
    # An expression index avoids persisting a duplicate copy of private page text.
    # The query uses the exact same expression and English regconfig.
    op.execute(
        "CREATE INDEX ix_rag_chunks_english_fts ON rag_chunks USING GIN "
        "(to_tsvector('english'::regconfig, "
        "coalesce(heading, '') || ' ' || text))"
    )
    op.create_index(
        "ix_rag_documents_project_type_scope",
        "rag_documents",
        ["project_id", "document_type", "access_scope"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_documents_project_type_scope", table_name="rag_documents")
    op.execute("DROP INDEX ix_rag_chunks_english_fts")
    op.drop_constraint("ck_rag_document_access", "rag_documents", type_="check")
    op.drop_constraint("ck_rag_document_type", "rag_documents", type_="check")
    op.drop_column("rag_documents", "access_scope")
    op.drop_column("rag_documents", "document_type")
