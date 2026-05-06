"""Restrict users writes to self or org admins.

Revision ID: 137_users_self_edit
Revises: 136_web_search_integration
Create Date: 2026-05-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "137_users_self_edit"
down_revision: Union[str, Sequence[str], None] = "136_web_search_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CURRENT_ORG_ID: str = """
COALESCE(
    NULLIF(current_setting('app.current_org_id', true), ''),
    '00000000-0000-0000-0000-000000000000'
)
""".strip()

_CURRENT_USER_ID: str = """
COALESCE(
    NULLIF(current_setting('app.current_user_id', true), ''),
    '00000000-0000-0000-0000-000000000000'
)
""".strip()

_USER_VISIBLE_IN_ORG: str = f"""
EXISTS (
    SELECT 1
    FROM org_members visible_membership
    WHERE visible_membership.user_id = users.id
      AND visible_membership.organization_id::text = {_CURRENT_ORG_ID}
)
""".strip()

_GUEST_VISIBLE_IN_ORG: str = f"""
(
    users.is_guest IS TRUE
    AND users.guest_organization_id IS NOT NULL
    AND users.guest_organization_id::text = {_CURRENT_ORG_ID}
)
""".strip()

_USER_VISIBLE: str = f"({_USER_VISIBLE_IN_ORG}) OR ({_GUEST_VISIBLE_IN_ORG})"

_USER_IS_SELF: str = f"users.id::text = {_CURRENT_USER_ID}"

_ADMIN_IN_CURRENT_ORG: str = f"""
EXISTS (
    SELECT 1
    FROM org_members admin_membership
    WHERE admin_membership.organization_id::text = {_CURRENT_ORG_ID}
      AND admin_membership.user_id::text = {_CURRENT_USER_ID}
      AND admin_membership.role = 'admin'
      AND admin_membership.status IN ('active', 'onboarding')
)
""".strip()

_CAN_EDIT_USER: str = f"({_USER_IS_SELF}) OR ({_ADMIN_IN_CURRENT_ORG})"


def upgrade() -> None:
    assert len(revision) <= 32
    assert isinstance(down_revision, str) and len(down_revision) <= 32

    # Avoid waiting indefinitely behind long-running user table writes.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS org_isolation ON users")
    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")

    op.execute(
        f"""
        CREATE POLICY users_select ON users
        FOR SELECT
        USING ({_USER_VISIBLE})
        """
    )

    # User creation is still orchestrated by application code. Existing RLS
    # table restrictions apply to subsequent edits once the row is part of an org.
    op.execute(
        """
        CREATE POLICY users_insert ON users
        FOR INSERT
        WITH CHECK (true)
        """
    )

    op.execute(
        f"""
        CREATE POLICY users_update ON users
        FOR UPDATE
        USING ({_USER_VISIBLE} AND ({_CAN_EDIT_USER}))
        WITH CHECK ({_USER_VISIBLE} AND ({_CAN_EDIT_USER}))
        """
    )

    op.execute(
        f"""
        CREATE POLICY users_delete ON users
        FOR DELETE
        USING ({_USER_VISIBLE} AND ({_ADMIN_IN_CURRENT_ORG}))
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")

    op.execute(
        f"""
        CREATE POLICY org_isolation ON users
        FOR ALL
        USING ({_USER_VISIBLE})
        """
    )
