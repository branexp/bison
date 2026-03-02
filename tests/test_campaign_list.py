from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from emailbison.cli import app


def _campaigns_page(
    campaigns: list[dict], *, current_page: int = 1, last_page: int = 1
) -> dict:
    return {
        "data": campaigns,
        "meta": {"current_page": current_page, "last_page": last_page, "total": len(campaigns)},
    }


@respx.mock
def test_list_campaigns_single_page(monkeypatch) -> None:
    """Single-page response returns all campaigns."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    campaigns = [
        {"id": 1, "name": "Campaign A", "status": "active"},
        {"id": 2, "name": "Campaign B", "status": "paused"},
    ]
    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "list"])

    assert result.exit_code == 0, result.output
    assert "id=1 status=active name=Campaign A" in result.output
    assert "id=2 status=paused name=Campaign B" in result.output


@respx.mock
def test_list_campaigns_multi_page(monkeypatch) -> None:
    """Multi-page response fetches all pages and returns all campaigns."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    page1 = [{"id": i, "name": f"Campaign {i}", "status": "active"} for i in range(1, 16)]
    page2 = [{"id": 16, "name": "Campaign 16", "status": "paused"}]

    route = respx.get("https://api.example.com/api/campaigns").mock(
        side_effect=[
            Response(200, json=_campaigns_page(page1, current_page=1, last_page=2)),
            Response(200, json=_campaigns_page(page2, current_page=2, last_page=2)),
        ]
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "list"])

    assert result.exit_code == 0, result.output
    assert route.call_count == 2
    # All 16 campaigns should be listed
    assert "id=1 status=active name=Campaign 1" in result.output
    assert "id=16 status=paused name=Campaign 16" in result.output


@respx.mock
def test_list_campaigns_json_output(monkeypatch) -> None:
    """JSON output includes all campaigns with meta.total."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    campaigns = [
        {"id": 10, "name": "My Campaign", "status": "completed"},
    ]
    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["--json", "campaign", "list"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["meta"]["total"] == 1
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == 10


@respx.mock
def test_list_campaigns_no_meta(monkeypatch) -> None:
    """Response without meta field still returns data (single page fallback)."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json={"data": [{"id": 5, "name": "X", "status": "draft"}]})
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "list"])

    assert result.exit_code == 0, result.output
    assert "id=5 status=draft name=X" in result.output


@respx.mock
def test_list_campaigns_auth_error(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "bad")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(401, json={"message": "Unauthorized"})
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "list"])

    assert result.exit_code == 3
