import asyncio

from agents import tools


def test_run_sql_write_blocks_users_table_updates():
    result = asyncio.run(
        tools._run_sql_write(
            params={"query": "UPDATE users SET phone_number = '+14155551234' WHERE id = 'abc'"},
            organization_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            context={"is_workflow": True},
        )
    )

    assert "error" in result
    assert "not in the writable list" in result["error"]
