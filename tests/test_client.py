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
    respx.post("https://api.example.com/api/campaigns").mock(return_value=Response(401, json={"error": "no"}))

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
