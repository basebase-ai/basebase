from __future__ import annotations

from uuid import UUID

import pytest

from connectors.apollo import ApolloConnector
from connectors.asana import AsanaConnector
from connectors.ispot_tv import ISpotTvConnector
from connectors.jira import JiraConnector
from connectors.linear import LinearConnector
from connectors.trello import TrelloConnector


@pytest.mark.parametrize(
    "connector_cls",
    [
        ApolloConnector,
        AsanaConnector,
        ISpotTvConnector,
        JiraConnector,
        LinearConnector,
        TrelloConnector,
    ],
)
def test_connector_constructors_accept_integration_filters(connector_cls: type) -> None:
    """Generic connector tools always pass multi-account filters into connector constructors."""
    integration_id = "11111111-1111-1111-1111-111111111111"

    connector = connector_cls(
        organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        integration_id=integration_id,
        account_identifier="linear-workspace",
    )

    assert connector._integration_id_filter == UUID(integration_id)
    assert connector._account_identifier_filter == "linear-workspace"
