"""Guest home org on guest_organization_id; drop users.organization_id.

Revision ID: 116_guest_org
Revises: 115_fix_notifications_rls_policy
Create Date: 2026-03-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "116_guest_org"
down_revision: Union[str, None] = "115_fix_notifications_rls_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "guest_organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE users SET guest_organization_id = organization_id "
            "WHERE is_guest IS TRUE AND organization_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET organization_id = NULL WHERE is_guest IS NOT TRUE"
        )
    )
    op.drop_index("uq_users_one_guest_per_org", table_name="users")
    op.create_index(
        "uq_users_one_guest_per_org",
        "users",
        ["guest_organization_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_guest = true AND guest_organization_id IS NOT NULL"
        ),
    )
    op.drop_column("users", "organization_id")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_guest_user_mutations()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.is_guest IS TRUE THEN
                    IF NEW.email IS DISTINCT FROM OLD.email THEN
                        RAISE EXCEPTION 'Guest user email is immutable';
                    END IF;

                    IF NEW.guest_organization_id IS DISTINCT FROM OLD.guest_organization_id THEN
                        RAISE EXCEPTION 'Guest user organization is immutable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE users SET organization_id = guest_organization_id "
            "WHERE is_guest IS TRUE AND guest_organization_id IS NOT NULL"
        )
    )
    op.drop_index("uq_users_one_guest_per_org", table_name="users")
    op.create_index(
        "uq_users_one_guest_per_org",
        "users",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_guest = true AND organization_id IS NOT NULL"
        ),
    )
    op.drop_column("users", "guest_organization_id")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_guest_user_mutations()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.is_guest IS TRUE THEN
                    IF NEW.email IS DISTINCT FROM OLD.email THEN
                        RAISE EXCEPTION 'Guest user email is immutable';
                    END IF;

                    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
                        RAISE EXCEPTION 'Guest user organization is immutable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
