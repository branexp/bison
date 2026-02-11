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


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return 0
    return 0


def _extract_metric(data: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in data:
            return _coerce_int(data.get(key))
    return 0


def _format_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))

    def fmt(row: list[str]) -> str:
        return " | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row))

    sep = "-+-".join("-" * width for width in widths)
    return [fmt(headers), sep] + [fmt(row) for row in rows]


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


@app.command("summary")
def campaign_summary(
    ctx: typer.Context,
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    status: str | None = typer.Option(None, "--status"),
    tag_ids: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Aggregate campaign stats across a date range."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.list_campaigns(status=status, tag_ids=tag_ids or None)
        data = raw.get("data")
        campaigns = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

        stat_keys = {
            "sent": ("emails_sent", "sent"),
            "delivered": ("emails_delivered", "delivered"),
            "opened": ("emails_opened", "opened"),
            "clicked": ("emails_clicked", "clicked"),
            "replied": ("emails_replied", "replied"),
            "bounced": ("emails_bounced", "bounced"),
        }

        totals = {key: 0 for key in stat_keys}
        rows_payload: list[dict[str, Any]] = []
        skipped: list[int] = []

        for row in campaigns:
            campaign_id = row.get("id")
            if not isinstance(campaign_id, int):
                typer.echo(f"Warning: skipping campaign with invalid id: {campaign_id}", err=True)
                continue

            name = row.get("name")
            status_value = row.get("status")

            try:
                stats_raw, _ = client.campaign_stats(
                    campaign_id, start_date=start_date, end_date=end_date
                )
            except AuthError as e:
                typer.echo(
                    f"Warning: failed to fetch stats for campaign {campaign_id}: {e}",
                    err=True,
                )
                skipped.append(campaign_id)
                continue
            except NetworkError as e:
                typer.echo(
                    f"Warning: failed to fetch stats for campaign {campaign_id}: {e}",
                    err=True,
                )
                skipped.append(campaign_id)
                continue
            except ApiError as e:
                typer.echo(
                    f"Warning: failed to fetch stats for campaign {campaign_id}: {e} "
                    f"Details: {json.dumps(e.details, indent=2)}",
                    err=True,
                )
                skipped.append(campaign_id)
                continue

            stats_data = stats_raw.get("data")
            if not isinstance(stats_data, dict):
                stats_data = {}

            metrics = {key: _extract_metric(stats_data, keys) for key, keys in stat_keys.items()}
            for key, value in metrics.items():
                totals[key] += value

            rows_payload.append(
                {
                    "campaign_id": campaign_id,
                    "name": name,
                    "status": status_value,
                    **metrics,
                }
            )

        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "tag_ids": tag_ids or None,
            "campaigns": rows_payload,
            "summary": totals,
            "skipped_campaign_ids": skipped,
        }

        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            headers = [
                "campaign_id",
                "name",
                "status",
                "sent",
                "delivered",
                "opened",
                "clicked",
                "replied",
                "bounced",
            ]
            table_rows: list[list[str]] = []
            for row in rows_payload:
                table_rows.append(
                    [
                        str(row.get("campaign_id", "")),
                        str(row.get("name") or ""),
                        str(row.get("status") or ""),
                        str(row.get("sent", 0)),
                        str(row.get("delivered", 0)),
                        str(row.get("opened", 0)),
                        str(row.get("clicked", 0)),
                        str(row.get("replied", 0)),
                        str(row.get("bounced", 0)),
                    ]
                )

            table_rows.append(
                [
                    "TOTAL",
                    "",
                    "",
                    str(totals["sent"]),
                    str(totals["delivered"]),
                    str(totals["opened"]),
                    str(totals["clicked"]),
                    str(totals["replied"]),
                    str(totals["bounced"]),
                ]
            )

            for line in _format_table(headers, table_rows):
                typer.echo(line)

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


@app.command("start")
def start_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip preflight checks (unsafe).",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Start a campaign (maps to resume). Performs basic safety checks by default."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        missing: list[str] = []

        details_raw, _ = client.campaign_details(campaign_id)
        data = details_raw.get("data")
        total_leads = None
        sequence_id = None
        status = None
        if isinstance(data, dict):
            if isinstance(data.get("total_leads"), int):
                total_leads = int(data.get("total_leads"))
            if isinstance(data.get("sequence_id"), int):
                sequence_id = int(data.get("sequence_id"))
            if isinstance(data.get("status"), str):
                status = str(data.get("status"))

        if not total_leads:
            missing.append("no leads attached")

        senders_raw, _ = client.get_campaign_sender_emails(campaign_id)
        sender_count = 0
        if isinstance(senders_raw.get("data"), list):
            sender_count = len(senders_raw.get("data"))
        if sender_count == 0:
            missing.append("no sender emails attached")

        seq_raw, _ = client.get_sequence_steps_v11(campaign_id)
        step_count = 0
        seq_data = seq_raw.get("data")
        if isinstance(seq_data, dict) and isinstance(seq_data.get("sequence_steps"), list):
            step_count = len(seq_data.get("sequence_steps"))
        if step_count == 0:
            missing.append("no sequence steps")

        preflight = {
            "ok": len(missing) == 0,
            "missing": missing,
            "campaign": {
                "id": campaign_id,
                "status": status,
                "sequence_id": sequence_id,
                "total_leads": total_leads,
            },
            "sender_emails_count": sender_count,
            "sequence_steps_count": step_count,
        }

        if missing and not force:
            if json_output:
                typer.echo(json.dumps({"preflight": preflight}, indent=2))
            else:
                typer.echo(
                    "Refusing to start campaign (preflight failed): " + ", ".join(missing),
                    err=True,
                )
            raise typer.Exit(code=2)

        resume_raw, _ = client.resume_campaign(campaign_id)
        details_after_raw, _ = client.campaign_details(campaign_id)

        payload = {
            "preflight": preflight,
            "resume": resume_raw,
            "campaign": details_after_raw,
        }

        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            new_status = None
            d2 = details_after_raw.get("data")
            if isinstance(d2, dict) and isinstance(d2.get("status"), str):
                new_status = str(d2.get("status"))
            typer.echo(f"id={campaign_id} started=true status={new_status or 'unknown'}")

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
