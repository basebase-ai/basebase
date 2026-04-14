"""Restrict org_members writes so non-admins can only edit themselves.

Revision ID: 133_org_members_self_edit
Revises: 132_wf_llm_model
Create Date: 2026-04-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "133_org_members_self_edit"
down_revision: Union[str, Sequence[str], None] = "132_wf_llm_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORG_MATCH: str = """
organization_id::text = COALESCE(
    NULLIF(current_setting('app.current_org_id', true), ''),
    '00000000-0000-0000-0000-000000000000'
)
""".strip()

_USER_MATCH: str = """
user_id::text = COALESCE(
    NULLIF(current_setting('app.current_user_id', true), ''),
    '00000000-0000-0000-0000-000000000000'
)
""".strip()

_ADMIN_IN_ORG: str = """
EXISTS (
    SELECT 1
    FROM org_members admin_membership
    WHERE admin_membership.organization_id = org_members.organization_id
      AND admin_membership.user_id::text = COALESCE(
          NULLIF(current_setting('app.current_user_id', true), ''),
          '00000000-0000-0000-0000-000000000000'
      )
      AND admin_membership.role = 'admin'
      AND admin_membership.status IN ('active', 'onboarding')
)
""".strip()

_CAN_EDIT_ROW: str = f"({_USER_MATCH}) OR ({_ADMIN_IN_ORG})"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_isolation ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_select ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_insert ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_update ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_delete ON org_members")

    op.execute(
        f"""
        CREATE POLICY org_members_select ON org_members
        FOR SELECT
        USING ({_ORG_MATCH})
        """
    )

    op.execute(
        f"""
        CREATE POLICY org_members_insert ON org_members
        FOR INSERT
        WITH CHECK ({_ORG_MATCH})
        """
    )

    op.execute(
        f"""
        CREATE POLICY org_members_update ON org_members
        FOR UPDATE
        USING ({_ORG_MATCH} AND ({_CAN_EDIT_ROW}))
        WITH CHECK ({_ORG_MATCH} AND ({_CAN_EDIT_ROW}))
        """
    )

    op.execute(
        f"""
        CREATE POLICY org_members_delete ON org_members
        FOR DELETE
        USING ({_ORG_MATCH} AND ({_CAN_EDIT_ROW}))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_members_select ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_insert ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_update ON org_members")
    op.execute("DROP POLICY IF EXISTS org_members_delete ON org_members")

    op.execute(
        f"""
        CREATE POLICY org_isolation ON org_members
        FOR ALL
        USING ({_ORG_MATCH})
        WITH CHECK ({_ORG_MATCH})
        """
    )
