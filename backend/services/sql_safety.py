"""Shared SQL read-safety checks for agent and app queries."""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
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


_FROM_CLAUSE_BOUNDARY_KEYWORDS: set[str] = {
    "where",
    "group",
    "having",
    "order",
    "limit",
    "offset",
    "union",
    "intersect",
    "except",
    "qualify",
    "window",
}


def _iter_from_clause_bodies(query: str) -> Iterator[str]:
    """Yield text after each FROM keyword up to the next top-level clause boundary."""
    for match in re.finditer(r'\bFROM\b', query, re.IGNORECASE):
        start = match.end()
        index = start
        depth = 0
        while index < len(query):
            char = query[index]
            if char in {"'", '"'}:
                quote = char
                index += 1
                while index < len(query):
                    if query[index] == quote:
                        if index + 1 < len(query) and query[index + 1] == quote:
                            index += 2
                            continue
                        index += 1
                        break
                    index += 1
                continue
            if char == '(':
                depth += 1
                index += 1
                continue
            if char == ')':
                if depth == 0:
                    break
                depth -= 1
                index += 1
                continue
            if depth == 0:
                keyword_match = re.match(r'[a-zA-Z_][a-zA-Z0-9_]*', query[index:])
                if keyword_match and keyword_match.group(0).lower() in _FROM_CLAUSE_BOUNDARY_KEYWORDS:
                    break
            index += 1
        yield query[start:index]


def _split_top_level_commas(clause: str) -> list[str]:
    """Split a FROM clause body on commas that are not nested or quoted."""
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(clause):
        char = clause[index]
        if char in {"'", '"'}:
            quote = char
            index += 1
            while index < len(clause):
                if clause[index] == quote:
                    if index + 1 < len(clause) and clause[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == '(':
            depth += 1
        elif char == ')' and depth > 0:
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(clause[start:index])
            start = index + 1
        index += 1
    parts.append(clause[start:])
    return parts


def _find_matching_parenthesis(sql: str, open_index: int = 0) -> int | None:
    """Return the index of the parenthesis matching ``open_index``."""
    depth = 0
    index = open_index
    while index < len(sql):
        char = sql[index]
        if char in {"'", '"'}:
            quote = char
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _iter_cte_names(query: str) -> Iterator[str]:
    """Yield CTE names declared by a leading WITH clause."""
    match = re.match(r'\s*WITH\b', query, re.IGNORECASE)
    if not match:
        return

    index = match.end()
    recursive_match = re.match(r'\s*RECURSIVE\b', query[index:], re.IGNORECASE)
    if recursive_match:
        index += recursive_match.end()

    while index < len(query):
        name_match = re.match(rf'\s*({_SQL_IDENTIFIER})', query[index:], re.IGNORECASE)
        if not name_match:
            return
        yield _normalize_table_identifier(name_match.group(1))
        index += name_match.end()

        # Optional column list after the CTE name: cte_name(col_a, col_b) AS (...).
        while index < len(query) and query[index].isspace():
            index += 1
        if index < len(query) and query[index] == '(':
            close_index = _find_matching_parenthesis(query, index)
            if close_index is None:
                return
            index = close_index + 1

        as_match = re.match(r'\s*AS\s*\(', query[index:], re.IGNORECASE)
        if not as_match:
            return
        open_index = index + as_match.end() - 1
        close_index = _find_matching_parenthesis(query, open_index)
        if close_index is None:
            return
        index = close_index + 1

        while index < len(query) and query[index].isspace():
            index += 1
        if index >= len(query) or query[index] != ',':
            return
        index += 1


def _is_unqualified_identifier(identifier: str) -> bool:
    """Return whether an identifier has no schema/database qualifier."""
    return not re.search(r'\s*\.\s*', identifier)


def _extract_table_references_from_from_item(clause_part: str) -> set[str]:
    """Return leading table identifiers from a comma-delimited FROM item."""
    stripped = clause_part.lstrip()
    if not stripped:
        return set()

    if stripped.startswith('('):
        close_index = _find_matching_parenthesis(stripped)
        if close_index is None:
            return set()
        inner = stripped[1:close_index]
        if re.match(r'\s*(?:SELECT|WITH|VALUES)\b', inner, re.IGNORECASE):
            return set()
        references: set[str] = set()
        for inner_part in _split_top_level_commas(inner):
            references.update(_extract_table_references_from_from_item(inner_part))
        return references

    match = re.match(rf'({_SQL_QUALIFIED_IDENTIFIER})', stripped, re.IGNORECASE)
    return {match.group(1)} if match else set()


def extract_tables_from_query(query: str) -> set[str]:
    """Extract table names from a SQL query (best effort)."""
    tables: set[str] = set()

    query = strip_sql_comments(query)
    cte_names = set(_iter_cte_names(query))

    # Match every explicit JOIN target, including schema-qualified tables like public.contacts.
    join_matches = re.findall(rf'\bJOIN\s+({_SQL_QUALIFIED_IDENTIFIER})', query, re.IGNORECASE)
    for match in join_matches:
        table_name = _normalize_table_identifier(match)
        if table_name in cte_names and _is_unqualified_identifier(match):
            continue
        tables.add(table_name)

    # FROM can introduce a comma-delimited table list; each item must be checked.
    for clause_body in _iter_from_clause_bodies(query):
        for clause_part in _split_top_level_commas(clause_body):
            table_references = _extract_table_references_from_from_item(clause_part)
            for table_reference in table_references:
                table_name = _normalize_table_identifier(table_reference)
                if table_name in cte_names and _is_unqualified_identifier(table_reference):
                    continue
                tables.add(table_name)

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
