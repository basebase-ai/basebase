"""Connector constructor compatibility tests."""
from __future__ import annotations

from uuid import UUID

from connectors.base import BaseConnector
from connectors.registry import discover_connectors


_ORG_ID = "00000000-0000-0000-0000-000000000001"
_USER_ID = "00000000-0000-0000-0000-000000000002"
_INTEGRATION_ID = "00000000-0000-0000-0000-000000000003"
_ACCOUNT_IDENTIFIER = "acct_constructor_scope"


def test_discovered_connectors_accept_integration_scope_kwargs() -> None:
    """All registry connectors must tolerate integration scoping kwargs.

    Dynamic connector callers pass these kwargs uniformly.  Connectors that do
    not need them should still forward them to BaseConnector so scoped DB
    lookups continue to work when the connector later calls shared helpers.
    """
    registry = discover_connectors()

    assert registry, "expected at least one discovered connector"

    for slug, connector_cls in registry.items():
        connector = connector_cls(
            _ORG_ID,
            user_id=_USER_ID,
            integration_id=_INTEGRATION_ID,
            account_identifier=_ACCOUNT_IDENTIFIER,
        )

        assert isinstance(connector, BaseConnector), slug
        assert connector._integration_id_filter == UUID(_INTEGRATION_ID), slug
        assert connector._account_identifier_filter == _ACCOUNT_IDENTIFIER, slug
