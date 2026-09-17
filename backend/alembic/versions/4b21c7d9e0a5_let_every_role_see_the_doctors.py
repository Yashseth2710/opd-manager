"""let every role see the doctors

Revision ID: 4b21c7d9e0a5
Revises: 38c8205b960e
Created: 2026-09-17 21:34:18.220411
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4b21c7d9e0a5"
down_revision: str | None = "38c8205b960e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "doctor:read"
DESCRIPTION = "View doctors and their hours"


def upgrade() -> None:
    """Backfills the permission for clinics that already exist.

    Roles are copied from the defaults when a clinic is created, so a clinic
    made yesterday would otherwise never learn about a permission added
    today. Booking, checking in and billing all start by choosing a doctor,
    so every role gets it rather than just the administrator's.

    It reaches a signed-in person when their access token is next reissued,
    which is within fifteen minutes.
    """
    op.execute(
        f"""
        INSERT INTO permissions (id, code, description)
        VALUES (gen_random_uuid(), '{CODE}', '{DESCRIPTION}')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), roles.id, permissions.id
        FROM roles
        CROSS JOIN permissions
        WHERE permissions.code = '{CODE}'
        ON CONFLICT ON CONSTRAINT uq_role_permissions_pair DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        USING permissions
        WHERE role_permissions.permission_id = permissions.id
          AND permissions.code = '{CODE}'
        """
    )
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
