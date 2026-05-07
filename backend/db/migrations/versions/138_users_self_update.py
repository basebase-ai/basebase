"""Restrict users writes to self, org admins, or global admins.

Revision ID: 138_users_self_update
Revises: 137_meeting_scope
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "138_users_self_update"
down_revision: Union[str, None] = "137_meeting_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_UUID: str = "00000000-0000-0000-0000-000000000000"

_CURRENT_ORG_ID: str = f"""
COALESCE(
    NULLIF(current_setting('app.current_org_id', true), ''),
    '{_EMPTY_UUID}'
)::uuid
""".strip()

_CURRENT_USER_ID: str = f"""
COALESCE(
    NULLIF(current_setting('app.current_user_id', true), ''),
    '{_EMPTY_UUID}'
)::uuid
""".strip()

_USER_VISIBLE_IN_ORG: str = f"""
EXISTS (
    SELECT 1
    FROM org_members m
    WHERE m.user_id = users.id
      AND m.organization_id = {_CURRENT_ORG_ID}
)
OR (
    users.is_guest IS TRUE
    AND users.guest_organization_id IS NOT NULL
    AND users.guest_organization_id = {_CURRENT_ORG_ID}
)
""".strip()

_USER_IS_SELF: str = f"users.id = {_CURRENT_USER_ID}"

_CAN_WRITE_USER: str = f"""
({_USER_IS_SELF})
OR current_app_user_is_org_admin({_CURRENT_ORG_ID})
OR current_app_user_is_global_admin()
""".strip()


_CURRENT_USER_IS_GLOBAL_ADMIN_FUNCTION: str = f"""
CREATE OR REPLACE FUNCTION current_app_user_is_global_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM users u
        WHERE u.id = {_CURRENT_USER_ID}
          AND (
              u.role = 'global_admin'
              OR COALESCE(u.roles, '[]'::jsonb) ? 'global_admin'
          )
    )
$$;
""".strip()

_CURRENT_USER_IS_ORG_ADMIN_FUNCTION: str = f"""
CREATE OR REPLACE FUNCTION current_app_user_is_org_admin(target_org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM org_members m
        WHERE m.organization_id = target_org_id
          AND m.user_id = {_CURRENT_USER_ID}
          AND m.role = 'admin'
          AND m.status IN ('active', 'onboarding')
    )
$$;
""".strip()


def upgrade() -> None:
    assert len(revision) <= 32
    assert isinstance(down_revision, str) and len(down_revision) <= 32

    op.execute(_CURRENT_USER_IS_GLOBAL_ADMIN_FUNCTION)
    op.execute(_CURRENT_USER_IS_ORG_ADMIN_FUNCTION)
    op.execute(
        "GRANT EXECUTE ON FUNCTION current_app_user_is_global_admin() TO revtops_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION current_app_user_is_org_admin(uuid) TO revtops_app"
    )

    op.execute("DROP POLICY IF EXISTS org_isolation ON users")
    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")

    op.execute(f"""
        CREATE POLICY users_select ON users
        FOR SELECT
        USING ({_USER_VISIBLE_IN_ORG})
        """)

    op.execute(f"""
        CREATE POLICY users_insert ON users
        FOR INSERT
        WITH CHECK (current_app_user_is_global_admin())
        """)

    op.execute(f"""
        CREATE POLICY users_update ON users
        FOR UPDATE
        USING (({_USER_VISIBLE_IN_ORG}) AND ({_CAN_WRITE_USER}))
        WITH CHECK (({_USER_VISIBLE_IN_ORG}) AND ({_CAN_WRITE_USER}))
        """)

    op.execute(f"""
        CREATE POLICY users_delete ON users
        FOR DELETE
        USING (current_app_user_is_global_admin())
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")

    op.execute(f"""
        CREATE POLICY org_isolation ON users
        FOR ALL
        USING ({_USER_VISIBLE_IN_ORG})
        """)

    op.execute(
        "REVOKE EXECUTE ON FUNCTION current_app_user_is_org_admin(uuid) FROM revtops_app"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION current_app_user_is_global_admin() FROM revtops_app"
    )
    op.execute("DROP FUNCTION IF EXISTS current_app_user_is_org_admin(uuid)")
    op.execute("DROP FUNCTION IF EXISTS current_app_user_is_global_admin()")
