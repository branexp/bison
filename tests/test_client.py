from __future__ import annotations

import pytest
import respx
from httpx import Response

from emailbison.client import ApiError, AuthError, EmailBisonClient
from emailbison.config import Settings


def _settings() -> Settings:
    return Settings(base_url="https://api.example.com", api_token="secret")


@respx.mock
def test_auth_error() -> None:
    respx.post("https://api.example.com/api/campaigns").mock(
        return_value=Response(401, json={"error": "no"})
    )

    client = EmailBisonClient(_settings())
    with pytest.raises(AuthError):
        client.create_campaign(name="x")
    client.close()


@respx.mock
def test_rate_limit_error() -> None:
    respx.post("https://api.example.com/api/campaigns").mock(
        return_value=Response(429, headers={"retry-after": "10"}, json={"error": "rl"})
    )

    client = EmailBisonClient(_settings())
    with pytest.raises(ApiError):
        client.create_campaign(name="x")
    client.close()


@respx.mock
def test_list_campaigns() -> None:
    respx.get("https://api.example.com/api/campaigns").mock(
        return_value=Response(200, json={"data": []})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.list_campaigns()
    assert raw["data"] == []
    client.close()


@respx.mock
def test_campaign_details_pause_resume_archive() -> None:
    respx.get("https://api.example.com/api/campaigns/123").mock(
        return_value=Response(200, json={"data": {"id": 123, "status": "draft"}})
    )
    respx.patch("https://api.example.com/api/campaigns/123/pause").mock(
        return_value=Response(200, json={"data": {"id": 123, "status": "paused"}})
    )
    respx.patch("https://api.example.com/api/campaigns/123/resume").mock(
        return_value=Response(200, json={"data": {"id": 123, "status": "queued"}})
    )
    respx.patch("https://api.example.com/api/campaigns/123/archive").mock(
        return_value=Response(200, json={"data": {"id": 123, "status": "archived"}})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.campaign_details(123)
    assert raw["data"]["id"] == 123

    raw, _ = client.pause_campaign(123)
    assert raw["data"]["status"] == "paused"

    raw, _ = client.resume_campaign(123)
    assert raw["data"]["status"] == "queued"

    raw, _ = client.archive_campaign(123)
    assert raw["data"]["status"] == "archived"

    client.close()


@respx.mock
def test_campaign_sender_emails_attach_remove() -> None:
    respx.get("https://api.example.com/api/campaigns/123/sender-emails").mock(
        return_value=Response(200, json={"data": [{"id": 1, "email": "a@b.com"}]})
    )
    respx.post("https://api.example.com/api/campaigns/123/attach-sender-emails").mock(
        return_value=Response(200, json={"success": True})
    )
    respx.delete("https://api.example.com/api/campaigns/123/remove-sender-emails").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())

    raw, _ = client.get_campaign_sender_emails(123)
    assert raw["data"][0]["id"] == 1

    raw, _ = client.attach_sender_emails(123, sender_email_ids=[1, 2])
    assert raw["success"] is True

    raw, _ = client.remove_sender_emails(123, sender_email_ids=[1])
    assert raw["success"] is True

    client.close()


@respx.mock
def test_campaign_stats_replies_stop_future_emails() -> None:
    respx.post("https://api.example.com/api/campaigns/123/stats").mock(
        return_value=Response(200, json={"data": {"emails_sent": "1"}})
    )
    respx.get("https://api.example.com/api/campaigns/123/replies").mock(
        return_value=Response(200, json={"data": [{"id": 9, "subject": "hi"}]})
    )
    respx.post("https://api.example.com/api/campaigns/123/leads/stop-future-emails").mock(
        return_value=Response(200, json={"data": {"success": True}})
    )

    client = EmailBisonClient(_settings())

    raw, _ = client.campaign_stats(123, start_date="2024-07-01", end_date="2024-07-19")
    assert raw["data"]["emails_sent"] == "1"

    raw, _ = client.campaign_replies(123, search="x")
    assert raw["data"][0]["id"] == 9

    raw, _ = client.stop_future_emails_for_leads(123, lead_ids=[1, 2, 3])
    assert raw["data"]["success"] is True

    client.close()


@respx.mock
def test_list_sender_emails() -> None:
    respx.get("https://api.example.com/api/sender-emails").mock(
        return_value=Response(200, json={"data": [{"id": 7, "email": "x@y.com"}]})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.list_sender_emails(search="x")
    assert raw["data"][0]["id"] == 7
    client.close()


@respx.mock
def test_sequence_get_set_update() -> None:
    respx.get("https://api.example.com/api/campaigns/v1.1/123/sequence-steps").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "sequence_id": 55,
                    "sequence_steps": [{"id": 9, "email_subject": "Hi", "order": 1}],
                }
            },
        )
    )

    respx.post("https://api.example.com/api/campaigns/v1.1/123/sequence-steps").mock(
        return_value=Response(200, json={"data": {"id": 55}})
    )

    respx.put("https://api.example.com/api/campaigns/v1.1/sequence-steps/55").mock(
        return_value=Response(200, json={"data": {"id": 55}})
    )

    client = EmailBisonClient(_settings())

    raw, _ = client.get_sequence_steps_v11(123)
    assert raw["data"]["sequence_id"] == 55

    raw, _ = client.create_sequence_steps_v11(123, {"title": "x", "sequence_steps": []})
    assert raw["data"]["id"] == 55

    raw, _ = client.update_sequence_steps_v11(55, {"title": "x", "sequence_steps": []})
    assert raw["data"]["id"] == 55

    client.close()


@respx.mock
def test_upload_leads_csv(tmp_path) -> None:
    csv_path = tmp_path / "district.csv"
    csv_path.write_text("first_name,last_name,email\nA,B,a@example.com\n", encoding="utf-8")

    route = respx.post("https://api.example.com/api/leads/bulk/csv").mock(
        return_value=Response(200, json={"data": {"id": 321, "status": "Unprocessed"}})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.upload_leads_csv(
        name="District A",
        csv_path=csv_path,
        columns_to_map={"first_name": "first_name", "last_name": "last_name", "email": "email"},
    )
    assert raw["data"]["id"] == 321
    assert route.called
    assert "multipart/form-data" in route.calls[0].request.headers.get("content-type", "")
    client.close()


@respx.mock
def test_get_lead_list_fallback_endpoint() -> None:
    respx.get("https://api.example.com/api/leads/lists/77").mock(
        return_value=Response(404, json={"error": "not found"})
    )
    respx.get("https://api.example.com/api/lead-lists/77").mock(
        return_value=Response(200, json={"data": {"id": 77, "status": "Processed"}})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.get_lead_list(77)
    assert raw["data"]["id"] == 77
    client.close()
