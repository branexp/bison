from __future__ import annotations

from unittest.mock import patch

import respx
from httpx import Response
from typer.testing import CliRunner

from emailbison.cli import app


def _leads_page(leads: list[dict], *, current_page: int = 1, last_page: int = 1) -> dict:
    return {
        "data": leads,
        "meta": {"current_page": current_page, "last_page": last_page},
    }


def _campaigns_page(
    campaigns: list[dict], *, current_page: int = 1, last_page: int = 1
) -> dict:
    return {
        "data": campaigns,
        "meta": {"current_page": current_page, "last_page": last_page},
    }


def _scheduled_page(items: list[dict], *, current_page: int = 1, last_page: int = 1) -> dict:
    return {
        "data": items,
        "meta": {"current_page": current_page, "last_page": last_page},
    }


def test_upload_leads_missing_db_url(monkeypatch) -> None:
    """upload-leads exits with code 2 when no database URL is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("BISON_DATABASE_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "upload-leads", "--all"])

    assert result.exit_code == 2
    assert "Database URL required" in result.output


def test_upload_leads_missing_campaign_or_all(monkeypatch) -> None:
    """upload-leads exits with code 2 when neither campaign ID nor --all is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("BISON_DATABASE_URL", "postgresql://fake/db")

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "upload-leads"])

    assert result.exit_code == 2
    assert "Provide a campaign ID or use --all" in result.output


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_leads")
def test_upload_leads_single_campaign(mock_upsert, monkeypatch) -> None:
    """upload-leads for a single campaign fetches leads and calls upsert_leads."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("BISON_DATABASE_URL", "postgresql://fake/db")

    mock_upsert.return_value = {"leads_upserted": 2, "campaign_memberships": 2}

    campaign_detail = {"data": {"id": 42, "name": "My Campaign", "total_leads": 2}}
    leads = [
        {
            "id": 1,
            "email": "a@example.com",
            "first_name": "A",
            "last_name": "B",
            "title": "",
            "company": "",
            "status": "active",
            "overall_stats": {"emails_sent": 1, "opens": 0, "replies": 0},
            "custom_variables": [],
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 2,
            "email": "c@example.com",
            "first_name": "C",
            "last_name": "D",
            "title": "",
            "company": "",
            "status": "active",
            "overall_stats": {"emails_sent": 2, "opens": 1, "replies": 0},
            "custom_variables": [],
            "created_at": None,
            "updated_at": None,
        },
    ]

    respx.get("https://api.example.com/api/campaigns/42").mock(
        return_value=Response(200, json=campaign_detail)
    )
    respx.get("https://api.example.com/api/campaigns/42/leads").mock(
        return_value=Response(200, json=_leads_page(leads))
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page([]))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "upload-leads", "42"])

    assert result.exit_code == 0, result.output
    assert "Uploaded 2 leads" in result.output
    mock_upsert.assert_called_once()


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_leads")
def test_upload_leads_all_campaigns(mock_upsert, monkeypatch) -> None:
    """upload-leads --all fetches all campaigns and uploads all leads."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("BISON_DATABASE_URL", "postgresql://fake/db")

    mock_upsert.return_value = {"leads_upserted": 1, "campaign_memberships": 1}

    campaigns = [{"id": 10, "name": "Camp A", "total_leads": 1}]
    leads = [
        {
            "id": 100,
            "email": "lead@example.com",
            "first_name": "Lead",
            "last_name": "One",
            "title": "",
            "company": "",
            "status": "active",
            "overall_stats": {},
            "custom_variables": [],
            "created_at": None,
            "updated_at": None,
        }
    ]

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )
    respx.get("https://api.example.com/api/campaigns/10/leads").mock(
        return_value=Response(200, json=_leads_page(leads))
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page([]))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "upload-leads", "--all"])

    assert result.exit_code == 0, result.output
    assert "Uploaded 1 leads" in result.output
    mock_upsert.assert_called_once()


@respx.mock
@patch("emailbison.commands.campaign_admin.init_db")
@patch("emailbison.commands.campaign_admin.upsert_leads")
def test_upload_leads_init_flag(mock_upsert, mock_init, monkeypatch) -> None:
    """--init flag calls init_db before uploading."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("BISON_DATABASE_URL", "postgresql://fake/db")

    mock_upsert.return_value = {"leads_upserted": 0, "campaign_memberships": 0}

    campaigns = [{"id": 20, "name": "Camp B", "total_leads": 0}]
    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "upload-leads", "--all", "--init"])

    # init_db should have been called
    mock_init.assert_called_once_with("postgresql://fake/db")
    assert "Schema initialized" in result.output


def test_db_stats_missing_url(monkeypatch) -> None:
    """db-stats exits with code 2 when no database URL is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("BISON_DATABASE_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "db-stats"])

    assert result.exit_code == 2
    assert "Database URL required" in result.output


@patch("emailbison.commands.campaign_admin.get_db_stats")
def test_db_stats_shows_output(mock_stats, monkeypatch) -> None:
    """db-stats prints stats from the database."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("BISON_DATABASE_URL", "postgresql://fake/db")

    mock_stats.return_value = {
        "total_leads": 100,
        "total_campaigns": 5,
        "total_memberships": 150,
        "by_status": {"active": 80, "unsubscribed": 20},
    }

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "db-stats"])

    assert result.exit_code == 0, result.output
    assert "Total leads: 100" in result.output
    assert "Total campaigns: 5" in result.output
    assert "Total memberships: 150" in result.output
    assert "active: 80" in result.output
    assert "unsubscribed: 20" in result.output
