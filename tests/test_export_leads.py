from __future__ import annotations

import csv

import respx
from httpx import Response
from typer.testing import CliRunner

from emailbison.cli import app


def _leads_page(leads: list[dict], *, current_page: int = 1, last_page: int = 1) -> dict:
    return {
        "data": leads,
        "meta": {"current_page": current_page, "last_page": last_page},
    }


def _scheduled_page(items: list[dict], *, current_page: int = 1, last_page: int = 1) -> dict:
    return {
        "data": items,
        "meta": {"current_page": current_page, "last_page": last_page},
    }


@respx.mock
def test_export_leads_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    leads = [
        {
            "id": 1,
            "email": "alice@example.com",
            "first_name": "Alice",
            "last_name": "Smith",
            "status": "active",
            "overall_stats": {"emails_sent": 3, "opens": 2, "replies": 1},
            "tags": [{"name": "Interested"}, {"name": "Automated Reply"}],
            "custom_variables": [
                {"name": "state", "value": "CA"},
                {"name": "company", "value": "Acme"},
            ],
        },
        {
            "id": 2,
            "email": "bob@example.com",
            "first_name": "Bob",
            "last_name": "Jones",
            "status": "unsubscribed",
            "overall_stats": {"emails_sent": 1, "opens": 0, "replies": 0},
            "tags": [],
            "custom_variables": [
                {"name": "state", "value": "TX"},
            ],
        },
    ]

    sent_emails = [
        {"lead_id": 1, "sent_at": "2024-07-10T10:00:00Z"},
        {"lead_id": 1, "sent_at": "2024-07-12T08:00:00Z"},  # more recent
        {"lead_id": 2, "sent_at": "2024-07-11T09:00:00Z"},
    ]

    respx.get("https://api.example.com/api/campaigns/42/leads").mock(
        return_value=Response(200, json=_leads_page(leads))
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page(sent_emails))
    )

    out_file = tmp_path / "leads.csv"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["campaign", "export-leads", "42", "--output", str(out_file)],
    )

    assert result.exit_code == 0, result.output
    assert "Exported 2 leads to" in result.output

    rows = list(csv.DictReader(out_file.open(encoding="utf-8")))
    assert len(rows) == 2

    alice = rows[0]
    assert alice["email"] == "alice@example.com"
    assert alice["first_name"] == "Alice"
    assert alice["last_name"] == "Smith"
    assert alice["status"] == "active"
    assert alice["emails_sent"] == "3"
    assert alice["opens"] == "2"
    assert alice["replies"] == "1"
    assert "Interested" in alice["tags"]
    assert "Automated Reply" in alice["tags"]
    assert alice["last_sent_date"] == "2024-07-12T08:00:00Z"
    assert alice["company"] == "Acme"
    assert alice["state"] == "CA"

    bob = rows[1]
    assert bob["email"] == "bob@example.com"
    assert bob["status"] == "unsubscribed"
    assert bob["tags"] == ""
    assert bob["last_sent_date"] == "2024-07-11T09:00:00Z"
    assert bob["state"] == "TX"
    assert bob["company"] == ""  # not present for bob, defaulted to empty


@respx.mock
def test_export_leads_pagination(tmp_path, monkeypatch) -> None:
    """Leads and scheduled-emails endpoints are both paginated correctly."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    page1_leads = [
        {
            "id": 10,
            "email": "p1@example.com",
            "first_name": "P",
            "last_name": "One",
            "status": "active",
            "overall_stats": {},
            "tags": [],
            "custom_variables": [],
        }
    ]
    page2_leads = [
        {
            "id": 11,
            "email": "p2@example.com",
            "first_name": "P",
            "last_name": "Two",
            "status": "bounced",
            "overall_stats": {},
            "tags": [],
            "custom_variables": [],
        }
    ]

    leads_route = respx.get("https://api.example.com/api/campaigns/5/leads").mock(
        side_effect=[
            Response(200, json=_leads_page(page1_leads, current_page=1, last_page=2)),
            Response(200, json=_leads_page(page2_leads, current_page=2, last_page=2)),
        ]
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page([]))
    )

    out_file = tmp_path / "leads.csv"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["campaign", "export-leads", "5", "--output", str(out_file)],
    )

    assert result.exit_code == 0, result.output
    assert "Exported 2 leads to" in result.output
    assert leads_route.call_count == 2

    rows = list(csv.DictReader(out_file.open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["email"] == "p1@example.com"
    assert rows[1]["email"] == "p2@example.com"


@respx.mock
def test_export_leads_default_output_filename(tmp_path, monkeypatch) -> None:
    """Default output path is campaign_{id}_leads.csv in cwd."""
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.chdir(tmp_path)

    respx.get("https://api.example.com/api/campaigns/99/leads").mock(
        return_value=Response(200, json=_leads_page([]))
    )
    respx.get("https://api.example.com/api/scheduled-emails").mock(
        return_value=Response(200, json=_scheduled_page([]))
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "export-leads", "99"])

    assert result.exit_code == 0, result.output
    assert "campaign_99_leads.csv" in result.output
    assert (tmp_path / "campaign_99_leads.csv").exists()


@respx.mock
def test_export_leads_api_error(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/campaigns/7/leads").mock(
        return_value=Response(500, json={"error": "server error"})
    )

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "export-leads", "7"])
    assert result.exit_code == 3
