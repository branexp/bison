from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from . import client_from_env

app = typer.Typer(add_completion=False)
tag_app = typer.Typer(add_completion=False)
app.add_typer(tag_app, name="tag")
_err = Console(stderr=True)


def _resolve_lead(client: EmailBisonClient, email: str) -> int:
    try:
        return client.get_lead_by_email(email)
    except ApiError as e:
        if e.status_code == 404:
            _err.print(f"[red]Lead not found for email: {email}[/red]")
            raise typer.Exit(code=1) from e
        raise


def _resolve_tag(client: EmailBisonClient, tag_name: str) -> int:
    try:
        return client.get_tag_id_by_name(tag_name)
    except ApiError as e:
        if e.status_code == 404:
            _err.print(f"[red]Tag not found: {tag_name}[/red]")
            raise typer.Exit(code=1) from e
        raise


@tag_app.command("add")
def tag_add(
    ctx: typer.Context,
    email: str = typer.Argument(..., help="Lead email address."),
    tag: str = typer.Option(..., "--tag", help="Workspace tag name to attach."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Attach a workspace tag to the lead associated with the given email."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        lead_id = _resolve_lead(client, email)
        tag_id = _resolve_tag(client, tag)
        raw, _ = client.attach_tag_to_leads(tag_id=tag_id, lead_ids=[lead_id])

        if json_output:
            typer.echo(json.dumps(raw, indent=2))

    except AuthError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=4) from e
    except ApiError as e:
        _err.print(f"[red]{e} Details: {json.dumps(e.details, indent=2)}[/red]")
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@tag_app.command("remove")
def tag_remove(
    ctx: typer.Context,
    email: str = typer.Argument(..., help="Lead email address."),
    tag: str = typer.Option(..., "--tag", help="Workspace tag name to remove."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Remove a workspace tag from the lead associated with the given email."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        lead_id = _resolve_lead(client, email)
        tag_id = _resolve_tag(client, tag)
        raw, _ = client.remove_tag_from_leads(tag_id=tag_id, lead_ids=[lead_id])

        if json_output:
            typer.echo(json.dumps(raw, indent=2))

    except AuthError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=4) from e
    except ApiError as e:
        _err.print(f"[red]{e} Details: {json.dumps(e.details, indent=2)}[/red]")
        raise typer.Exit(code=3) from e
    finally:
        client.close()


def _load_vars(json_str: str | None, file_path: Path | None) -> dict[str, Any]:
    if json_str is not None and file_path is not None:
        _err.print("[red]Provide only one of --json or --file, not both.[/red]")
        raise typer.Exit(code=2)
    if json_str is not None:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            _err.print(f"[red]Invalid JSON string: {e}[/red]")
            raise typer.Exit(code=2) from e
        if not isinstance(data, dict):
            _err.print("[red]JSON input must be an object (dict).[/red]")
            raise typer.Exit(code=2)
        return data
    if file_path is not None:
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except FileNotFoundError as e:
            _err.print(f"[red]File not found: {file_path}[/red]")
            raise typer.Exit(code=2) from e
        except json.JSONDecodeError as e:
            _err.print(f"[red]Invalid JSON in file {file_path}: {e}[/red]")
            raise typer.Exit(code=2) from e
        if not isinstance(data, dict):
            _err.print("[red]JSON file must contain an object (dict).[/red]")
            raise typer.Exit(code=2)
        return data
    _err.print("[red]Provide either --json or --file.[/red]")
    raise typer.Exit(code=2)


@app.command("update-vars")
def update_vars(
    ctx: typer.Context,
    email: str = typer.Argument(..., help="Lead email address."),
    json_str: str | None = typer.Option(None, "--json", help="JSON object of variables."),
    file_path: Path | None = typer.Option(None, "--file", help="Path to JSON file of variables."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Update custom variables on the lead associated with the given email."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    variables = _load_vars(json_str, file_path)

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        lead_id = _resolve_lead(client, email)
        raw, _ = client.update_lead_vars(lead_id, variables)

        if json_output:
            typer.echo(json.dumps(raw, indent=2))

    except AuthError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=4) from e
    except ApiError as e:
        _err.print(f"[red]{e} Details: {json.dumps(e.details, indent=2)}[/red]")
        raise typer.Exit(code=3) from e
    finally:
        client.close()
