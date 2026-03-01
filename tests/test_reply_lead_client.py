from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from emailbison.client import ApiError, EmailBisonClient
from emailbison.config import Settings


def _settings() -> Settings:
    return Settings(base_url="https://api.example.com", api_token="secret")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


@respx.mock
def test_get_lead_by_email_found() -> None:
    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(
            200,
            json={"data": [{"id": 42, "email": "user@example.com"}]},
        )
    )

    client = EmailBisonClient(_settings())
    lead_id = client.get_lead_by_email("user@example.com")
    assert lead_id == 42
    client.close()


@respx.mock
def test_get_lead_by_email_case_insensitive() -> None:
    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(
            200,
            json={"data": [{"id": 42, "email": "User@Example.COM"}]},
        )
    )

    client = EmailBisonClient(_settings())
    lead_id = client.get_lead_by_email("user@example.com")
    assert lead_id == 42
    client.close()


@respx.mock
def test_get_lead_by_email_not_found() -> None:
    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": []})
    )

    client = EmailBisonClient(_settings())
    with pytest.raises(ApiError) as exc_info:
        client.get_lead_by_email("nobody@example.com")
    assert exc_info.value.status_code == 404
    client.close()


@respx.mock
def test_get_latest_reply_for_lead() -> None:
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(
            200,
            json={"data": [{"id": 99, "subject": "hello"}, {"id": 88, "subject": "old"}]},
        )
    )

    client = EmailBisonClient(_settings())
    reply_id = client.get_latest_reply_for_lead(42)
    assert reply_id == 99
    client.close()


@respx.mock
def test_get_latest_reply_for_lead_none() -> None:
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": []})
    )

    client = EmailBisonClient(_settings())
    with pytest.raises(ApiError) as exc_info:
        client.get_latest_reply_for_lead(42)
    assert exc_info.value.status_code == 404
    client.close()


@respx.mock
def test_get_tag_id_by_name_found() -> None:
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(
            200,
            json={"data": [{"id": 7, "name": "High Priority"}, {"id": 8, "name": "Cold"}]},
        )
    )

    client = EmailBisonClient(_settings())
    tag_id = client.get_tag_id_by_name("High Priority")
    assert tag_id == 7
    client.close()


@respx.mock
def test_get_tag_id_by_name_case_insensitive() -> None:
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(200, json={"data": [{"id": 7, "name": "High Priority"}]})
    )

    client = EmailBisonClient(_settings())
    tag_id = client.get_tag_id_by_name("high priority")
    assert tag_id == 7
    client.close()


@respx.mock
def test_get_tag_id_by_name_not_found() -> None:
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(200, json={"data": []})
    )

    client = EmailBisonClient(_settings())
    with pytest.raises(ApiError) as exc_info:
        client.get_tag_id_by_name("Missing Tag")
    assert exc_info.value.status_code == 404
    client.close()


# ---------------------------------------------------------------------------
# Reply status toggles
# ---------------------------------------------------------------------------


@respx.mock
def test_mark_reply_interested() -> None:
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-interested").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.mark_reply_interested(99)
    assert raw["success"] is True
    assert route.called
    client.close()


@respx.mock
def test_mark_reply_not_interested() -> None:
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-not-interested").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.mark_reply_not_interested(99)
    assert raw["success"] is True
    assert route.called
    client.close()


@respx.mock
def test_mark_reply_read() -> None:
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-read-or-unread").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.mark_reply_read(99, is_read=True)
    assert raw["success"] is True
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"is_read": True}
    client.close()


@respx.mock
def test_mark_reply_unread() -> None:
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-read-or-unread").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.mark_reply_read(99, is_read=False)
    assert raw["success"] is True
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"is_read": False}
    client.close()


# ---------------------------------------------------------------------------
# Lead workspace tags
# ---------------------------------------------------------------------------


@respx.mock
def test_attach_tag_to_leads() -> None:
    route = respx.post("https://api.example.com/api/tags/attach-to-leads").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.attach_tag_to_leads(tag_id=7, lead_ids=[42])
    assert raw["success"] is True
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"tag_id": 7, "lead_ids": [42]}
    client.close()


@respx.mock
def test_remove_tag_from_leads() -> None:
    route = respx.post("https://api.example.com/api/tags/remove-from-leads").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.remove_tag_from_leads(tag_id=7, lead_ids=[42])
    assert raw["success"] is True
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"tag_id": 7, "lead_ids": [42]}
    client.close()


# ---------------------------------------------------------------------------
# Lead variable editing
# ---------------------------------------------------------------------------


@respx.mock
def test_update_lead_vars() -> None:
    route = respx.patch("https://api.example.com/api/leads/42").mock(
        return_value=Response(200, json={"success": True})
    )

    client = EmailBisonClient(_settings())
    raw, _ = client.update_lead_vars(42, {"company": "Acme", "timezone": "EST"})
    assert raw["success"] is True
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"variables": {"company": "Acme", "timezone": "EST"}}
    client.close()
