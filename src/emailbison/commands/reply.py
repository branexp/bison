from __future__ import annotations

import json

import typer
from rich.console import Console

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from . import client_from_env

app = typer.Typer(add_completion=False)
_err = Console(stderr=True)


def _resolve_reply(client: EmailBisonClient, email: str) -> int:
    try:
        lead_id = client.get_lead_by_email(email)
    except ApiError as e:
        if e.status_code == 404:
            _err.print(f"[red]Lead not found for email: {email}[/red]")
            raise typer.Exit(code=1) from e
        raise
    try:
        reply_id = client.get_latest_reply_for_lead(lead_id)
    except ApiError as e:
        if e.status_code == 404:
            _err.print(f"[red]No replies found for lead with email: {email}[/red]")
            raise typer.Exit(code=1) from e
        raise
    return reply_id


@app.command("mark-interested")
def mark_interested(
    ctx: typer.Context,
    email: str = typer.Argument(..., help="Lead email address."),
    not_interested: bool = typer.Option(False, "--not-interested", help="Mark as not interested."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Mark the latest reply for a lead as interested (or not interested)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        reply_id = _resolve_reply(client, email)
        if not_interested:
            raw, _ = client.mark_reply_not_interested(reply_id)
        else:
            raw, _ = client.mark_reply_interested(reply_id)

        if json_output:
            typer.echo(json.dumps(raw, indent=2))

    except AuthError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=4) from e
    except ApiError as e:
        _err.print(f"{e} Details: {json.dumps(e.details, indent=2)}", style="red", markup=False)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("mark-read")
def mark_read(
    ctx: typer.Context,
    email: str = typer.Argument(..., help="Lead email address."),
    unread: bool = typer.Option(False, "--unread", help="Mark as unread instead of read."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Mark the latest reply for a lead as read (or unread)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        reply_id = _resolve_reply(client, email)
        raw, _ = client.mark_reply_read(reply_id, is_read=not unread)

        if json_output:
            typer.echo(json.dumps(raw, indent=2))

    except AuthError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=4) from e
    except ApiError as e:
        _err.print(f"{e} Details: {json.dumps(e.details, indent=2)}", style="red", markup=False)
        raise typer.Exit(code=3) from e
    finally:
        client.close()
