"""Shared SQL read-safety checks for agent and app queries."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from access_control import RightsContext, check_sql

logger = logging.getLogger(__name__)

ALLOWED_TABLES: set[str] = {
    "deals", "accounts", "contacts", "activities", "meetings", "integrations", "users", "organizations",
    "org_members", "apps",
    "conversations", "chat_messages",
    "pipelines", "pipeline_stages", "goals", "workflows", "workflow_runs", "user_mappings_for_identity",
    "github_repositories", "github_commits", "github_pull_requests",
    "shared_files",
    "tracker_teams", "tracker_projects", "tracker_issues",
    "bulk_operations", "bulk_operation_results",
    "temp_data",
    "daily_digests", "daily_team_summaries",
}

_SQL_BUILTIN_FUNCTIONS: set[str] = {
    # Date/time functions that might appear after FROM in expressions
    "now", "current_date", "current_time", "current_timestamp",
    "localtime", "localtimestamp", "date", "time", "timestamp",
    "extract", "date_part", "date_trunc", "age", "interval",
    # Other common functions that could be mistaken for tables
    "generate_series", "unnest", "json_each", "json_array_elements",
    "jsonb_each", "jsonb_array_elements", "regexp_matches",
    "string_to_array", "lateral", "rows",
}


@dataclass(frozen=True)
class SafeSqlQuery:
    """SQL query after shared safety and rights checks."""

    query: str
    params: dict[str, Any] | None
    tables: set[str]


def strip_sql_comments(query: str) -> str:
    """Remove SQL comments (-- line comments and /* block comments */) from a query."""
    # Remove block comments /* ... */
    query = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)
    # Remove line comments -- ...
    query = re.sub(r'--[^\n]*', '', query)
    return query.strip()


def validate_sql_query(query: str) -> tuple[bool, str | None]:
    """
    Validate that the SQL query is safe to execute.
    Returns (is_valid, error_message).
    """
    # Strip comments before validation so queries like "-- comment\nSELECT ..." pass
    query_no_comments: str = strip_sql_comments(query)
    query_upper = query_no_comments.upper().strip()

    # Must start with SELECT (or WITH for CTEs)
    if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
        return False, "Only SELECT queries are allowed"

    # Block dangerous keywords
    dangerous_keywords: list[str] = [
        "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER",
        "CREATE", "GRANT", "REVOKE", "EXECUTE", "EXEC",
        "INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE",
    ]
    for keyword in dangerous_keywords:
        # Check for keyword as whole word (not part of column name)
        if re.search(rf'\b{keyword}\b', query_upper):
            return False, f"'{keyword}' statements are not allowed"

    return True, None


_SQL_IDENTIFIER = r'(?:(?:"[^"]+")|(?:[a-zA-Z_][a-zA-Z0-9_]*))'
_SQL_QUALIFIED_IDENTIFIER = rf'{_SQL_IDENTIFIER}(?:\s*\.\s*{_SQL_IDENTIFIER})*'


def _normalize_table_identifier(identifier: str) -> str:
    """Return the table/object name from a possibly schema-qualified identifier."""
    table_name = re.split(r'\s*\.\s*', identifier)[-1]
    return table_name.strip('"').lower()


def extract_tables_from_query(query: str) -> set[str]:
    """Extract table names from a SQL query (best effort)."""
    tables: set[str] = set()

    # Match FROM and JOIN clauses, including schema-qualified tables like public.contacts.
    patterns = [
        rf'\bFROM\s+({_SQL_QUALIFIED_IDENTIFIER})',
        rf'\bJOIN\s+({_SQL_QUALIFIED_IDENTIFIER})',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, query, re.IGNORECASE)
        tables.update(_normalize_table_identifier(match) for match in matches)

    # Exclude SQL built-in functions that might be mistaken for tables
    tables -= _SQL_BUILTIN_FUNCTIONS

    return tables


async def prepare_safe_sql_query(
    *,
    query: str,
    organization_id: str,
    user_id: str | None,
    params: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    is_workflow: bool = False,
    log_prefix: str = "SQL",
) -> tuple[SafeSqlQuery | None, str | None]:
    """Run shared read-query validation, table allowlist, and rights checks."""
    is_valid, error = validate_sql_query(query)
    if not is_valid:
        logger.warning("[%s] Query validation failed: %s", log_prefix, error)
        return None, error

    tables: set[str] = extract_tables_from_query(query)
    logger.debug("[%s] Detected tables: %s", log_prefix, tables)

    disallowed: set[str] = tables - ALLOWED_TABLES
    if disallowed:
        logger.warning("[%s] Query used disallowed tables: %s", log_prefix, disallowed)
        return None, f"Access to tables not allowed: {disallowed}"

    rights_ctx = RightsContext(
        organization_id=organization_id,
        user_id=user_id,
        conversation_id=conversation_id,
        is_workflow=is_workflow,
    )
    rights_result = await check_sql(rights_ctx, query, params)
    if not rights_result.allowed:
        logger.warning("[%s] Rights check denied SQL: %s", log_prefix, rights_result.deny_reason)
        return None, rights_result.deny_reason or "SQL not allowed"

    query_to_run: str = rights_result.transformed_query if rights_result.transformed_query is not None else query
    params_to_use: dict[str, Any] | None = rights_result.transformed_params if rights_result.transformed_params is not None else params
    return SafeSqlQuery(query=query_to_run, params=params_to_use, tables=tables), None
