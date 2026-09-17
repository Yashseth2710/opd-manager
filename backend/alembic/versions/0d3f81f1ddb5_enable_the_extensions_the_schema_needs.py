"""enable the extensions the schema needs

Revision ID: 0d3f81f1ddb5
Revises:
Created: 2026-09-16 12:41:42.011871
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0d3f81f1ddb5"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # btree_gist backs the exclusion constraint that stops two receptionists
    # booking the same doctor for the same slot. pg_trgm backs fuzzy patient
    # search and duplicate detection.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
