from agents import tools


def test_scope_org_members_update_to_current_user() -> None:
    query = "UPDATE org_members SET title = 'CEO' WHERE id = 'membership-1'"

    scoped_query, error = tools._scope_org_member_write_to_user(
        query=query,
        operation="UPDATE",
        user_id="00000000-0000-0000-0000-000000000123",
    )

    assert error is None
    assert scoped_query is not None
    assert "AND user_id = '00000000-0000-0000-0000-000000000123'" in scoped_query


def test_scope_org_members_insert_rejects_other_user_id() -> None:
    query = (
        "INSERT INTO org_members (organization_id, user_id, role) VALUES "
        "('org-1', '00000000-0000-0000-0000-000000000999', 'member')"
    )

    scoped_query, error = tools._scope_org_member_write_to_user(
        query=query,
        operation="INSERT",
        user_id="00000000-0000-0000-0000-000000000123",
    )

    assert scoped_query is None
    assert error == "Non-admin users can only write their own org_members row."


def test_scope_org_members_insert_injects_user_id_when_missing() -> None:
    query = "INSERT INTO org_members (organization_id, role) VALUES ('org-1', 'member')"

    scoped_query, error = tools._scope_org_member_write_to_user(
        query=query,
        operation="INSERT",
        user_id="00000000-0000-0000-0000-000000000123",
    )

    assert error is None
    assert scoped_query is not None
    assert "(organization_id, role, user_id)" in scoped_query
    assert "'00000000-0000-0000-0000-000000000123'" in scoped_query
