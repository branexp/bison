from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from emailbison.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# reply mark-interested
# ---------------------------------------------------------------------------


@respx.mock
def test_reply_mark_interested(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": [{"id": 99}]})
    )
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-interested").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(app, ["reply", "mark-interested", "user@example.com"])
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_reply_mark_not_interested(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": [{"id": 99}]})
    )
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-not-interested").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(
        app, ["reply", "mark-interested", "user@example.com", "--not-interested"]
    )
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_reply_mark_interested_json_output(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": [{"id": 99}]})
    )
    respx.patch("https://api.example.com/api/replies/99/mark-as-interested").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(app, ["--json", "reply", "mark-interested", "user@example.com"])
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["success"] is True


@respx.mock
def test_reply_mark_interested_lead_not_found(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": []})
    )

    result = runner.invoke(app, ["reply", "mark-interested", "nobody@example.com"])
    assert result.exit_code == 1


@respx.mock
def test_reply_mark_interested_no_replies(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": []})
    )

    result = runner.invoke(app, ["reply", "mark-interested", "user@example.com"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# reply mark-read
# ---------------------------------------------------------------------------


@respx.mock
def test_reply_mark_read(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": [{"id": 99}]})
    )
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-read-or-unread").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(app, ["reply", "mark-read", "user@example.com"])
    assert result.exit_code == 0
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"is_read": True}


@respx.mock
def test_reply_mark_unread(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/leads/42/replies").mock(
        return_value=Response(200, json={"data": [{"id": 99}]})
    )
    route = respx.patch("https://api.example.com/api/replies/99/mark-as-read-or-unread").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(app, ["reply", "mark-read", "user@example.com", "--unread"])
    assert result.exit_code == 0
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"is_read": False}


# ---------------------------------------------------------------------------
# lead tag add / remove
# ---------------------------------------------------------------------------


@respx.mock
def test_lead_tag_add(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(200, json={"data": [{"id": 7, "name": "High Priority"}]})
    )
    route = respx.post("https://api.example.com/api/tags/attach-to-leads").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(
        app, ["lead", "tag", "add", "user@example.com", "--tag", "High Priority"]
    )
    assert result.exit_code == 0
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"tag_id": 7, "lead_ids": [42]}


@respx.mock
def test_lead_tag_remove(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(200, json={"data": [{"id": 7, "name": "High Priority"}]})
    )
    route = respx.post("https://api.example.com/api/tags/remove-from-leads").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(
        app, ["lead", "tag", "remove", "user@example.com", "--tag", "High Priority"]
    )
    assert result.exit_code == 0
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"tag_id": 7, "lead_ids": [42]}


@respx.mock
def test_lead_tag_add_tag_not_found(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    respx.get("https://api.example.com/api/tags").mock(
        return_value=Response(200, json={"data": []})
    )

    result = runner.invoke(
        app, ["lead", "tag", "add", "user@example.com", "--tag", "Ghost Tag"]
    )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# lead update-vars
# ---------------------------------------------------------------------------


@respx.mock
def test_lead_update_vars_json(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    route = respx.patch("https://api.example.com/api/leads/42").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(
        app,
        ["lead", "update-vars", "user@example.com", "--vars", '{"company": "Acme"}'],
    )
    assert result.exit_code == 0
    assert route.called
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"variables": {"company": "Acme"}}


@respx.mock
def test_lead_update_vars_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    vars_file = tmp_path / "vars.json"
    vars_file.write_text('{"timezone": "EST"}', encoding="utf-8")

    respx.get("https://api.example.com/api/leads").mock(
        return_value=Response(200, json={"data": [{"id": 42, "email": "user@example.com"}]})
    )
    route = respx.patch("https://api.example.com/api/leads/42").mock(
        return_value=Response(200, json={"success": True})
    )

    result = runner.invoke(
        app,
        ["lead", "update-vars", "user@example.com", "--file", str(vars_file)],
    )
    assert result.exit_code == 0
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload == {"variables": {"timezone": "EST"}}


def test_lead_update_vars_no_input(monkeypatch) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    result = runner.invoke(app, ["lead", "update-vars", "user@example.com"])
    assert result.exit_code == 2


def test_lead_update_vars_both_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EMAILBISON_API_TOKEN", "secret")
    monkeypatch.setenv("EMAILBISON_BASE_URL", "https://api.example.com")

    vars_file = tmp_path / "vars.json"
    vars_file.write_text('{"k": "v"}', encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "lead",
            "update-vars",
            "user@example.com",
            "--vars",
            '{"k": "v"}',
            "--file",
            str(vars_file),
        ],
    )
    assert result.exit_code == 2
