"""Add purchase_orders, po_matches tables; content hash in document tags.

Revision ID: 0003
Revises: 0002
Create Date: 2025-03-01 00:00:00.000000
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op

revision  = "0003"
down_revision = "0002"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id",           sa.String(36),  primary_key=True),
        sa.Column("po_number",    sa.String(255), nullable=False),
        sa.Column("vendor_name",  sa.String(255), nullable=False),
        sa.Column("total_amount", sa.Float,       nullable=True),
        sa.Column("currency",     sa.String(10),  nullable=False, server_default="GBP"),
        sa.Column("line_items",   sa.JSON,        nullable=False, server_default="[]"),
        sa.Column("status",       sa.String(40),  nullable=False, server_default="open"),
        sa.Column("tenant_id",    sa.String(80),  nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_po_number", "purchase_orders", ["po_number"])
    op.create_index("ix_po_vendor", "purchase_orders", ["vendor_name"])
    op.create_index("ix_po_tenant", "purchase_orders", ["tenant_id"])

    op.create_table(
        "po_matches",
        sa.Column("id",             sa.String(36), primary_key=True),
        sa.Column("document_id",    sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("po_id",          sa.String(36), sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("match_status",   sa.String(40), nullable=False, server_default="unmatched"),
        sa.Column("match_score",    sa.Float,      nullable=False, server_default="0.0"),
        sa.Column("discrepancies",  sa.JSON,       nullable=False, server_default="[]"),
        sa.Column("matched_fields", sa.JSON,       nullable=False, server_default="{}"),
        sa.Column("created_at",     sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("po_matches")
    op.drop_table("purchase_orders")
