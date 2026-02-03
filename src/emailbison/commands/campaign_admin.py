from __future__ import annotations

import json
from typing import Any

import typer

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from ..config import ConfigError, load_settings

app = typer.Typer(add_completion=False)


def _client_from_env(*, base_url: str | None, debug: bool) -> EmailBisonClient:
    try:
        settings = load_settings(base_url=base_url)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    return EmailBisonClient(settings, debug=debug)


def _dump_or_human(
    *,
    payload: dict[str, Any],
    json_output: bool,
    human_lines: list[str] | None = None,
) -> None:
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    if human_lines:
        for line in human_lines:
            typer.echo(line)
        return

    typer.echo(payload)


@app.command("list")
def list_campaigns(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search"),
    status: str | None = typer.Option(None, "--status"),
    tag_id: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.list_campaigns(search=search, status=status, tag_ids=tag_id or None)

        data = raw.get("data")
        lines: list[str] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                cid = row.get("id")
                name = row.get("name")
                st = row.get("status")
                lines.append(f"id={cid} status={st} name={name}")

        _dump_or_human(payload=raw, json_output=json_output, human_lines=lines)

    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("get")
def get_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.campaign_details(campaign_id)
        _dump_or_human(payload=raw, json_output=json_output)
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("pause")
def pause_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.pause_campaign(campaign_id)
        _dump_or_human(payload=raw, json_output=json_output)
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("resume")
def resume_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.resume_campaign(campaign_id)
        _dump_or_human(payload=raw, json_output=json_output)
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("archive")
def archive_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.archive_campaign(campaign_id)
        _dump_or_human(payload=raw, json_output=json_output)
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()
