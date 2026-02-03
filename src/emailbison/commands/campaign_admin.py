from __future__ import annotations

import json
from typing import Any

import typer

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from ..config import ConfigError, load_settings

app = typer.Typer(add_completion=False)


def _require_non_empty_int_list(values: list[int] | None, *, what: str) -> list[int]:
    vals = values or []
    if not vals:
        typer.echo(f"Missing at least one {what} (repeatable).", err=True)
        raise typer.Exit(code=2)
    return vals


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


@app.command("sender-emails")
def campaign_sender_emails(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """List sender email accounts attached to a campaign."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.get_campaign_sender_emails(campaign_id)

        data = raw.get("data")
        lines: list[str] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                sid = row.get("id")
                email = row.get("email")
                status = row.get("status")
                lines.append(f"id={sid} status={status} email={email}")

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


@app.command("attach-sender-emails")
def attach_sender_emails(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    sender_email_id: list[int] | None = typer.Option(
        None,
        "--sender-email-id",
        help="Repeatable sender email id to attach.",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Attach sender email accounts to a campaign."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    ids = _require_non_empty_int_list(sender_email_id, what="--sender-email-id")

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.attach_sender_emails(campaign_id, sender_email_ids=ids)
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


@app.command("remove-sender-emails")
def remove_sender_emails(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    sender_email_id: list[int] | None = typer.Option(
        None,
        "--sender-email-id",
        help="Repeatable sender email id to remove.",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Remove sender email accounts from a campaign (draft/paused only)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    ids = _require_non_empty_int_list(sender_email_id, what="--sender-email-id")

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.remove_sender_emails(campaign_id, sender_email_ids=ids)
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


@app.command("stats")
def campaign_stats(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Get campaign stats summary for a date range."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.campaign_stats(campaign_id, start_date=start_date, end_date=end_date)
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


@app.command("replies")
def campaign_replies(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    search: str | None = typer.Option(None, "--search"),
    status: str | None = typer.Option(None, "--status"),
    folder: str | None = typer.Option(None, "--folder"),
    read: bool | None = typer.Option(None, "--read/--unread"),
    sender_email_id: int | None = typer.Option(None, "--sender-email-id"),
    lead_id: int | None = typer.Option(None, "--lead-id"),
    tag_id: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """List replies for a campaign."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.campaign_replies(
            campaign_id,
            search=search,
            status=status,
            folder=folder,
            read=read,
            sender_email_id=sender_email_id,
            lead_id=lead_id,
            tag_ids=tag_id or None,
        )

        data = raw.get("data")
        lines: list[str] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                rid = row.get("id")
                subj = row.get("subject")
                frm = row.get("from_email_address")
                lines.append(f"id={rid} from={frm} subject={subj}")

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


@app.command("stop-future-emails")
def stop_future_emails(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    lead_id: list[int] | None = typer.Option(
        None,
        "--lead-id",
        help="Repeatable lead id.",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Stop future emails for selected leads in a campaign."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    lead_ids = _require_non_empty_int_list(lead_id, what="--lead-id")

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.stop_future_emails_for_leads(campaign_id, lead_ids=lead_ids)
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
