from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from emailbison.cli import app


@respx.mock
def test_create_batch_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("emailbison.commands.campaign.time.sleep", lambda _: None)

    csv_dir = tmp_path / "districts"
    csv_dir.mkdir()
    (csv_dir / "district_a.csv").write_text(
        "first_name,last_name,email,district_name\n"
        "Alex,One,a1@example.com,District A\n"
        "Blair,Two,b2@example.com,District A\n",
        encoding="utf-8",
    )

    sequence_file = tmp_path / "sequence.json"
    sequence_file.write_text(
        json.dumps(
            {
                "title": "District Sequence",
                "sequence_steps": [
                    {"email_subject": "Hi", "email_body": "Body 1", "wait_in_days": 1},
                    {"email_subject": "Follow up", "email_body": "Body 2", "wait_in_days": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"max_emails_per_day": 100}), encoding="utf-8")
    schedule_file = tmp_path / "schedule.json"
    schedule_file.write_text(
        json.dumps(
            {
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "start_time": "09:00",
                "end_time": "17:00",
                "timezone": "America/New_York",
                "save_as_template": False,
            }
        ),
        encoding="utf-8",
    )

    respx.post("https://api.example.com/api/leads/bulk/csv").mock(
        return_value=Response(200, json={"data": {"id": 501, "status": "Unprocessed"}})
    )
    respx.get("https://api.example.com/api/leads/lists/501").mock(
        side_effect=[
            Response(200, json={"data": {"id": 501, "status": "Processing"}}),
            Response(200, json={"data": {"id": 501, "status": "Processed"}}),
        ]
    )
    respx.post("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json={"data": {"id": 900, "status": "draft"}})
    )
    respx.patch("https://api.example.com/api/campaigns/900/update").mock(
        return_value=Response(200, json={"data": {"id": 900}})
    )
    respx.post("https://api.example.com/api/campaigns/900/schedule").mock(
        return_value=Response(200, json={"data": {"id": 900}})
    )
    respx.post("https://api.example.com/api/campaigns/v1.1/900/sequence-steps").mock(
        return_value=Response(200, json={"data": {"id": 33}})
    )
    respx.post("https://api.example.com/api/campaigns/900/attach-sender-emails").mock(
        return_value=Response(200, json={"success": True})
    )
    respx.post("https://api.example.com/api/campaigns/900/leads/attach-lead-list").mock(
        return_value=Response(200, json={"success": True})
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "campaign",
            "create-batch",
            "--dir",
            str(csv_dir),
            "--sequence-file",
            str(sequence_file),
            "--settings-file",
            str(settings_file),
            "--schedule-file",
            str(schedule_file),
            "--sender-email-id",
            "11",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "summary: total_processed=1 succeeded=1 failed=0 leads_loaded=2" in result.output


@respx.mock
def test_create_batch_skip_and_continue_on_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")
    monkeypatch.setattr("emailbison.commands.campaign.time.sleep", lambda _: None)

    csv_dir = tmp_path / "districts"
    csv_dir.mkdir()
    (csv_dir / "district_a.csv").write_text(
        "first_name,last_name,email,district_name\nA,One,a@example.com,District A\n",
        encoding="utf-8",
    )
    (csv_dir / "district_b.csv").write_text(
        "first_name,last_name,email,district_name\nB,Two,b@example.com,District B\n",
        encoding="utf-8",
    )

    respx.post("https://api.example.com/api/leads/bulk/csv").mock(
        side_effect=[
            Response(200, json={"data": {"id": 601, "status": "Processed"}}),
            Response(200, json={"data": {"id": 602, "status": "Processed"}}),
        ]
    )
    respx.post("https://api.example.com/api/campaigns/901/attach-sender-emails").mock(
        return_value=Response(200, json={"success": True})
    )
    respx.post("https://api.example.com/api/campaigns/901/leads/attach-lead-list").mock(
        return_value=Response(200, json={"success": True})
    )
    # Second file fails while creating campaign.
    respx.post("https://api.example.com/api/campaigns").mock(
        side_effect=[
            Response(200, json={"data": {"id": 901, "status": "draft"}}),
            Response(500, json={"error": "boom"}),
        ]
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "campaign",
            "create-batch",
            "--dir",
            str(csv_dir),
            "--sender-email-id",
            "11",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "summary: total_processed=2 succeeded=1 failed=1 leads_loaded=1" in result.output
