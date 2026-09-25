"""put every clinic on a plan

Revision ID: 5d2e8b41c7fa
Revises: 163a5509e40e
Created: 2026-09-25 14:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5d2e8b41c7fa"
down_revision: str | None = "163a5509e40e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied rather than imported, so this migration keeps doing what it did on
# the day it was written.
PLANS = """
INSERT INTO subscription_plans (id, slug, name, description, price_monthly, limits, position)
VALUES
  (gen_random_uuid(), 'starter', 'Starter', 'One or two doctors getting going.', 0,
   '{"max_doctors": 2, "max_staff": 5, "max_patients": 1000,
     "max_appointments_per_month": 600, "max_storage_mb": 500}', 1),
  (gen_random_uuid(), 'clinic', 'Clinic', 'A busy practice with a front desk.', 1499,
   '{"max_doctors": 8, "max_staff": 25, "max_patients": 20000,
     "max_appointments_per_month": 5000, "max_storage_mb": 5120}', 2),
  (gen_random_uuid(), 'group', 'Group',
   'Several consultants under one roof, with nothing capped.', 4999,
   '{"max_doctors": null, "max_staff": null, "max_patients": null,
     "max_appointments_per_month": null, "max_storage_mb": null}', 3)
ON CONFLICT (slug) DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_monthly", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "organization_subscriptions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index(
        op.f("ix_organization_subscriptions_plan_id"),
        "organization_subscriptions",
        ["plan_id"],
        unique=False,
    )

    op.execute(PLANS)
    # Clinics made before there were plans keep everything they had. Nothing
    # they already do starts being refused because a limit arrived after them.
    op.execute(
        """
        INSERT INTO organization_subscriptions (id, organization_id, plan_id)
        SELECT gen_random_uuid(), o.id, p.id
        FROM organizations o CROSS JOIN subscription_plans p
        WHERE p.slug = 'group'
        ON CONFLICT (organization_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_subscriptions_plan_id"), table_name="organization_subscriptions"
    )
    op.drop_table("organization_subscriptions")
    op.drop_table("subscription_plans")
