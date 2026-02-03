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
