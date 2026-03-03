from __future__ import annotations

import json

import typer

from ._shared import client_from_env, dump_or_human
from ..client import ApiError, AuthError, NetworkError

app = typer.Typer(add_completion=False)


@app.command("list")
def list_sender_emails(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search"),
    tag_id: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    excluded_tag_id: list[int] | None = typer.Option(None, "--excluded-tag-id", help="Repeatable."),
    without_tags: bool | None = typer.Option(None, "--without-tags/--with-tags"),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """List sender email accounts for the workspace."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.list_sender_emails(
            search=search,
            tag_ids=tag_id or None,
            excluded_tag_ids=excluded_tag_id or None,
            without_tags=without_tags,
        )

        data = raw.get("data")
        lines: list[str] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                sid = row.get("id")
                email = row.get("email")
                status = row.get("status")
                daily = row.get("daily_limit")
                lines.append(f"id={sid} status={status} daily_limit={daily} email={email}")

        dump_or_human(payload=raw, json_output=json_output, human_lines=lines)

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
