from pathlib import Path


DATASOURCES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "DataSources.tsx"


def test_shared_with_team_pill_renders_in_connector_rows() -> None:
    source = DATASOURCES.read_text()

    assert "const renderSharedWithTeamPill = (integration: DisplayIntegration)" in source
    assert "if (!isSharedWithTeam(integration)) return null;" in source
    assert "{renderSharedWithTeamPill(integration)}" in source


def test_shared_with_team_pill_uses_any_sharing_flag() -> None:
    source = DATASOURCES.read_text()

    assert "const isSharedWithTeam = (sharing:" in source
    assert "sharing.shareSyncedData || sharing.shareQueryAccess || sharing.shareWriteAccess" in source
    assert "const sharedPill = renderSharedWithTeamPill(integration);" in source
