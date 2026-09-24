"""let a patient pay a bill from a link

Revision ID: 7e5c1a9d43b2
Revises: 3cd9da72b11b
Created: 2026-09-24 11:42:19.508311
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7e5c1a9d43b2"
down_revision: str | None = "3cd9da72b11b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Everything taken so far was taken at the desk, which is what the
    # default says; it comes off afterwards so the column is set explicitly
    # from here on.
    op.add_column(
        "payments",
        sa.Column("channel", sa.String(length=8), nullable=False, server_default="desk"),
    )
    op.alter_column("payments", "channel", server_default=None)
    op.create_check_constraint(
        "ck_payment_channel", "payments", "channel IN ('desk', 'online')"
    )

    op.create_table(
        "payment_links",
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("gateway_payment_id", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("excess_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_to", sa.String(length=255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_link_amount"),
        sa.CheckConstraint("excess_amount >= 0", name="ck_payment_link_excess"),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)", name="ck_payment_link_paid"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'paid', 'cancelled', 'expired')",
            name="ck_payment_link_status",
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_link_invoice", "payment_links", ["invoice_id", "created_at"], unique=False
    )
    op.create_index("ix_payment_link_order", "payment_links", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_payment_links_organization_id"),
        "payment_links",
        ["organization_id"],
        unique=False,
    )
    op.create_index("uq_payment_link_token", "payment_links", ["token_hash"], unique=True)
    op.create_index(
        "uq_payment_link_open",
        "payment_links",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "uq_payment_link_gateway",
        "payment_links",
        ["organization_id", "gateway_payment_id"],
        unique=True,
        postgresql_where=sa.text("gateway_payment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_payment_link_gateway",
        table_name="payment_links",
        postgresql_where=sa.text("gateway_payment_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_payment_link_open",
        table_name="payment_links",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index("uq_payment_link_token", table_name="payment_links")
    op.drop_index(op.f("ix_payment_links_organization_id"), table_name="payment_links")
    op.drop_index("ix_payment_link_order", table_name="payment_links")
    op.drop_index("ix_payment_link_invoice", table_name="payment_links")
    op.drop_table("payment_links")
    op.drop_constraint("ck_payment_channel", "payments", type_="check")
    op.drop_column("payments", "channel")
