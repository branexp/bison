"""Tests for the sync-leads CLI command and related db-stats command."""

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


def test_sync_leads_missing_db_url(monkeypatch) -> None:
    """sync-leads exits with code 2 when no database URL is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("PERA_DATABASE_URL", raising=False)
    monkeypatch.delenv("BISON_DATABASE_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "sync-leads", "--all"])

    assert result.exit_code == 2
    assert "Database URL required" in result.output


def test_sync_leads_missing_campaign_or_all(monkeypatch) -> None:
    """sync-leads exits with code 2 when neither campaign ID nor --all is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "sync-leads"])

    assert result.exit_code == 2
    assert "Provide a campaign ID or use --all" in result.output


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_campaigns")
@patch("emailbison.commands.campaign_admin.upsert_leads")
@patch("emailbison.commands.campaign_admin.upsert_contact_campaigns")
def test_sync_leads_single_campaign(
    mock_upsert_cc, mock_upsert_leads, mock_upsert_campaigns, monkeypatch
) -> None:
    """sync-leads for a single campaign fetches leads and calls upsert functions."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_upsert_campaigns.return_value = {"campaigns_upserted": 1}
    mock_upsert_leads.return_value = {
        "leads_upserted": 2,
        "contacts_updated": 1,
        "skipped_no_contactid": 1,
    }
    mock_upsert_cc.return_value = {"memberships_upserted": 1}

    campaign_detail = {"data": {"id": 42, "name": "My Campaign", "total_leads": 2}}
    leads = [
        {
            "id": 1,
            "email": "a@example.com",
            "first_name": "A",
            "last_name": "B",
            "title": "Teacher",
            "company": "School A",
            "status": "active",
            "overall_stats": {"emails_sent": 1, "opens": 0, "replies": 0},
            "custom_variables": [{"name": "contactid", "value": "100"}],
            "tags": [],
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
            "tags": [],
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
    result = runner.invoke(app, ["campaign", "sync-leads", "42"])

    assert result.exit_code == 0, result.output
    assert "Sync complete" in result.output
    mock_upsert_campaigns.assert_called_once()
    mock_upsert_leads.assert_called_once()
    mock_upsert_cc.assert_called_once()


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_campaigns")
@patch("emailbison.commands.campaign_admin.upsert_leads")
@patch("emailbison.commands.campaign_admin.upsert_contact_campaigns")
def test_sync_leads_all_campaigns(
    mock_upsert_cc, mock_upsert_leads, mock_upsert_campaigns, monkeypatch
) -> None:
    """sync-leads --all fetches all campaigns and syncs all leads."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_upsert_campaigns.return_value = {"campaigns_upserted": 1}
    mock_upsert_leads.return_value = {
        "leads_upserted": 1,
        "contacts_updated": 1,
        "skipped_no_contactid": 0,
    }
    mock_upsert_cc.return_value = {"memberships_upserted": 1}

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
            "custom_variables": [{"name": "contactid", "value": "200"}],
            "tags": [],
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
    result = runner.invoke(app, ["campaign", "sync-leads", "--all"])

    assert result.exit_code == 0, result.output
    assert "Sync complete" in result.output
    mock_upsert_campaigns.assert_called_once()
    mock_upsert_leads.assert_called_once()
    mock_upsert_cc.assert_called_once()


@respx.mock
@patch("emailbison.commands.campaign_admin.init_db")
@patch("emailbison.commands.campaign_admin.upsert_campaigns")
@patch("emailbison.commands.campaign_admin.upsert_leads")
@patch("emailbison.commands.campaign_admin.upsert_contact_campaigns")
def test_sync_leads_init_flag(
    mock_upsert_cc, mock_upsert_leads, mock_upsert_campaigns, mock_init, monkeypatch
) -> None:
    """--init flag calls init_db before syncing."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_upsert_campaigns.return_value = {"campaigns_upserted": 0}
    mock_upsert_leads.return_value = {
        "leads_upserted": 0, "contacts_updated": 0, "skipped_no_contactid": 0
    }
    mock_upsert_cc.return_value = {"memberships_upserted": 0}

    campaigns = [{"id": 20, "name": "Camp B", "total_leads": 0}]
    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "sync-leads", "--all", "--init"])

    mock_init.assert_called_once_with("postgresql://fake/db")
    assert "Schema initialized" in result.output


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_campaigns")
@patch("emailbison.commands.campaign_admin.upsert_leads")
@patch("emailbison.commands.campaign_admin.upsert_contact_campaigns")
def test_sync_leads_extracts_contactid_from_custom_variables(
    mock_upsert_cc, mock_upsert_leads, mock_upsert_campaigns, monkeypatch
) -> None:
    """sync-leads extracts contactid from custom_variables and builds memberships."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_upsert_campaigns.return_value = {"campaigns_upserted": 1}
    mock_upsert_leads.return_value = {
        "leads_upserted": 1, "contacts_updated": 1, "skipped_no_contactid": 0
    }
    mock_upsert_cc.return_value = {"memberships_upserted": 1}

    campaigns = [{"id": 5, "name": "Test", "total_leads": 1}]
    leads = [
        {
            "id": 99,
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "title": "Principal",
            "company": "Big School",
            "status": "active",
            "overall_stats": {"emails_sent": 5, "opens": 3, "replies": 1},
            "custom_variables": [
                {"name": "contactid", "value": "777"},
                {"name": "state", "value": "MA"},
            ],
            "tags": [{"name": "prospect"}],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-06-01T00:00:00Z",
        }
    ]

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )
    respx.get("https://api.example.com/api/campaigns/5/leads").mock(
        return_value=Response(200, json=_leads_page(leads))
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page([]))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "sync-leads", "--all"])

    assert result.exit_code == 0, result.output

    # Check that upsert_leads was called with correct contact_id
    leads_call_args = mock_upsert_leads.call_args[0]
    leads_list = leads_call_args[1]
    assert len(leads_list) == 1
    assert leads_list[0]["contact_id"] == 777
    assert leads_list[0]["tags"] == ["prospect"]

    # Check membership was built
    memberships = mock_upsert_cc.call_args[0][1]
    assert len(memberships) == 1
    assert memberships[0]["contact_id"] == 777
    assert memberships[0]["campaign_id"] == 5
    assert memberships[0]["lead_id"] == 99


def test_db_stats_missing_url(monkeypatch) -> None:
    """db-stats exits with code 2 when no database URL is provided."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("PERA_DATABASE_URL", raising=False)
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
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_stats.return_value = {
        "total_campaigns": 3,
        "total_leads": 100,
        "leads_with_contact": 80,
        "leads_without_contact": 20,
        "total_memberships": 150,
        "by_status": {"active": 80, "unsubscribed": 20},
        "last_sync": None,
    }

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "db-stats"])

    assert result.exit_code == 0, result.output
    assert "Total campaigns: 3" in result.output
    assert "Total leads: 100" in result.output
    assert "Leads with contact: 80" in result.output
    assert "Leads without contact: 20" in result.output
    assert "Total memberships: 150" in result.output
    assert "active: 80" in result.output
    assert "unsubscribed: 20" in result.output


@respx.mock
@patch("emailbison.commands.campaign_admin.upsert_campaigns")
@patch("emailbison.commands.campaign_admin.upsert_leads")
@patch("emailbison.commands.campaign_admin.upsert_contact_campaigns")
def test_sync_leads_per_campaign_last_sent(
    mock_upsert_cc, mock_upsert_leads, mock_upsert_campaigns, monkeypatch
) -> None:
    """last_sent_date for each membership is the most recent send in THAT campaign only."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("PERA_DATABASE_URL", "postgresql://fake/db")

    mock_upsert_campaigns.return_value = {"campaigns_upserted": 2}
    mock_upsert_leads.return_value = {
        "leads_upserted": 1, "contacts_updated": 1, "skipped_no_contactid": 0
    }
    mock_upsert_cc.return_value = {"memberships_upserted": 2}

    campaigns = [
        {"id": 10, "name": "Camp A", "total_leads": 1},
        {"id": 20, "name": "Camp B", "total_leads": 1},
    ]
    lead = {
        "id": 100,
        "email": "l@example.com",
        "first_name": "L",
        "last_name": "M",
        "title": "",
        "company": "",
        "status": "active",
        "overall_stats": {},
        "custom_variables": [{"name": "contactid", "value": "500"}],
        "tags": [],
        "created_at": None,
        "updated_at": None,
    }

    sent_camp10 = [{"lead": {"id": 100}, "sent_at": "2024-07-10T00:00:00Z"}]
    sent_camp20 = [{"lead": {"id": 100}, "sent_at": "2024-08-01T00:00:00Z"}]

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page(campaigns))
    )
    respx.get("https://api.example.com/api/campaigns/10/leads").mock(
        return_value=Response(200, json=_leads_page([lead]))
    )
    respx.get("https://api.example.com/api/campaigns/20/leads").mock(
        return_value=Response(200, json=_leads_page([lead]))
    )

    def _scheduled_side_effect(request, route):
        if "campaign_ids%5B%5D=10" in str(request.url) or "campaign_ids[]=10" in str(request.url):
            return Response(200, json=_scheduled_page(sent_camp10))
        return Response(200, json=_scheduled_page(sent_camp20))

    respx.get("https://api.example.com/api/scheduled-emails").mock(
        side_effect=_scheduled_side_effect
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "sync-leads", "--all"])

    assert result.exit_code == 0, result.output
    mock_upsert_cc.assert_called_once()

    memberships = mock_upsert_cc.call_args[0][1]
    assert len(memberships) == 2

    by_cid = {m["campaign_id"]: m for m in memberships}
    assert by_cid[10]["last_sent_date"] == "2024-07-10T00:00:00Z"
    assert by_cid[20]["last_sent_date"] == "2024-08-01T00:00:00Z"


@respx.mock
def test_export_all_leads_invalid_campaign_ids_flag(monkeypatch) -> None:
    """--campaign-ids with non-integer values exits with code 2."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json=_campaigns_page([]))
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["campaign", "export-all-leads", "--campaign-ids", "abc,1"]
    )

    assert result.exit_code == 2
    assert "Invalid --campaign-ids" in result.output
