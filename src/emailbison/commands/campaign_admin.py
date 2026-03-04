from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import typer

from ..client import ApiError, AuthError, NetworkError
from ..pera_client import (
    DatabaseError,
    get_campaign_stats,
    get_leads_by_status_per_campaign,
    get_meeting_booking_rate_by_state,
    init_db,
    upsert_campaigns,
    upsert_contact_campaigns,
    upsert_leads,
)
from ..pera_client import (
    get_sync_stats as get_db_stats,
)
from ._shared import client_from_env, dump_or_human

app = typer.Typer(add_completion=False)


def _require_non_empty_int_list(values: list[int] | None, *, what: str) -> list[int]:
    vals = values or []
    if not vals:
        typer.echo(f"Missing at least one {what} (repeatable).", err=True)
        raise typer.Exit(code=2)
    return vals


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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        all_campaigns, _ = client.list_all_campaigns(
            search=search, status=status, tag_ids=tag_id or None
        )

        lines: list[str] = []
        for row in all_campaigns:
            if not isinstance(row, dict):
                continue
            cid = row.get("id")
            name = row.get("name")
            st = row.get("status")
            lines.append(f"id={cid} status={st} name={name}")

        if json_output:
            payload: dict[str, Any] = {"data": all_campaigns, "meta": {"total": len(all_campaigns)}}
            typer.echo(json.dumps(payload, indent=2))
        else:
            for line in lines:
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

    client = client_from_env(base_url=base_url, debug=debug)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.campaign_details(campaign_id)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.pause_campaign(campaign_id)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.resume_campaign(campaign_id)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.archive_campaign(campaign_id)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.attach_sender_emails(campaign_id, sender_email_ids=ids)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.remove_sender_emails(campaign_id, sender_email_ids=ids)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.campaign_stats(campaign_id, start_date=start_date, end_date=end_date)
        dump_or_human(payload=raw, json_output=json_output)
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

    client = client_from_env(base_url=base_url, debug=debug)
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

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.stop_future_emails_for_leads(campaign_id, lead_ids=lead_ids)
        dump_or_human(payload=raw, json_output=json_output)
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


@app.command("export-leads")
def export_leads(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output CSV file path (default: campaign_{id}_leads.csv).",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Export all leads from a campaign to an enriched CSV file."""

    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    if json_output:
        typer.echo(
            "JSON output (--json) is not supported for 'export-leads'; "
            "omit --json to export leads to CSV.",
            err=True,
        )
        raise typer.Exit(code=2)
    out_path = output or Path(f"campaign_{campaign_id}_leads.csv")

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        # 1. Fetch all leads (paginated)
        leads: list[dict[str, Any]] = []
        page = 1
        while True:
            raw, _ = client.list_campaign_leads(campaign_id, page=page)
            data = raw.get("data")
            if isinstance(data, list):
                leads.extend(data)
            meta = raw.get("meta")
            if not isinstance(meta, dict):
                break
            last_page = meta.get("last_page")
            if not isinstance(last_page, int) or page >= last_page:
                break
            page += 1

        # 2. Fetch sent scheduled emails to build last_sent_date mapping per lead
        last_sent: dict[int, str] = {}
        page = 1
        while True:
            raw, _ = client.list_scheduled_emails(campaign_id, status="sent", page=page)
            data = raw.get("data")
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    lead_obj = item.get("lead")
                    lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
                    sent_at = item.get("sent_at")
                    if isinstance(lead_id, int) and isinstance(sent_at, str):
                        existing = last_sent.get(lead_id)
                        if existing is None or sent_at > existing:
                            last_sent[lead_id] = sent_at
            meta = raw.get("meta")
            if not isinstance(meta, dict):
                break
            last_page = meta.get("last_page")
            if not isinstance(last_page, int) or page >= last_page:
                break
            page += 1

        # 3. Collect all unique custom variable names across leads, sorted alphabetically
        seen_cv: set[str] = set()
        for lead in leads:
            for cv in lead.get("custom_variables") or []:
                if isinstance(cv, dict):
                    name = cv.get("name")
                    if isinstance(name, str):
                        seen_cv.add(name)

        # 4. Write CSV
        fixed_fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "title",
            "company",
            "status",
            "emails_sent",
            "opens",
            "replies",
            "tags",
            "last_sent_date",
            "created_at",
            "updated_at",
        ]
        fixed_fields_set = set(fixed_fields)
        custom_var_names = sorted(name for name in seen_cv if name not in fixed_fields_set)
        fieldnames = fixed_fields + custom_var_names

        with out_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for lead in leads:
                lead_id = lead.get("id")

                tags_val = ", ".join(
                    t.get("name", "") for t in (lead.get("tags") or []) if isinstance(t, dict)
                )

                overall_stats = lead.get("overall_stats") or {}
                if not isinstance(overall_stats, dict):
                    overall_stats = {}

                cv_map: dict[str, str] = {}
                for cv in lead.get("custom_variables") or []:
                    if isinstance(cv, dict):
                        name = cv.get("name")
                        value = cv.get("value")
                        if isinstance(name, str) and name not in fixed_fields_set:
                            cv_map[name] = str(value) if value is not None else ""

                row: dict[str, Any] = {
                    "id": lead_id,
                    "email": lead.get("email", ""),
                    "first_name": lead.get("first_name", ""),
                    "last_name": lead.get("last_name", ""),
                    "title": lead.get("title", ""),
                    "company": lead.get("company", ""),
                    "status": lead.get("status", ""),
                    "emails_sent": overall_stats.get("emails_sent", ""),
                    "opens": overall_stats.get("opens", ""),
                    "replies": overall_stats.get("replies", ""),
                    "tags": tags_val,
                    "last_sent_date": last_sent.get(lead_id, "")
                    if isinstance(lead_id, int)
                    else "",
                    "created_at": lead.get("created_at", ""),
                    "updated_at": lead.get("updated_at", ""),
                    **cv_map,
                }
                writer.writerow(row)

        typer.echo(f"Exported {len(leads)} leads to {out_path}")

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


@app.command("export-all-leads")
def export_all_leads(
    ctx: typer.Context,
    output: Path = typer.Option(
        "all_leads.csv",
        "--output",
        "-o",
        help="Output CSV file path.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter campaigns by status (paused, completed, draft, etc.)",
    ),
    campaign_ids: str | None = typer.Option(
        None,
        "--campaign-ids",
        help="Comma-separated list of campaign IDs to export (default: all with leads)",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Export leads from all campaigns to a single CSV file."""
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False

    if json_output:
        typer.echo("JSON output not supported for bulk export.", err=True)
        raise typer.Exit(code=2)

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        typer.echo("Fetching campaigns...", err=True)
        all_campaign_list, _ = client.list_all_campaigns(status=status)

        if campaign_ids:
            try:
                requested_ids = {
                    int(cid.strip()) for cid in campaign_ids.split(",") if cid.strip()
                }
            except ValueError:
                typer.echo(
                    "Invalid --campaign-ids: expected comma-separated integers, e.g. '1,2,3'.",
                    err=True,
                )
                raise typer.Exit(code=2) from None
            campaigns_to_export = [
                c
                for c in all_campaign_list
                if isinstance(c, dict)
                and isinstance(c.get("id"), int)
                and c["id"] in requested_ids
                and c.get("total_leads", 0) > 0
            ]
        else:
            campaigns_to_export = [
                c
                for c in all_campaign_list
                if isinstance(c, dict) and c.get("total_leads", 0) > 0
            ]

        if not campaigns_to_export:
            typer.echo("No campaigns with leads found.", err=True)
            raise typer.Exit(code=0)

        typer.echo(f"Exporting {len(campaigns_to_export)} campaigns...", err=True)

        all_leads: dict[int, dict[str, Any]] = {}
        lead_campaign_ids: dict[int, list[int]] = {}
        all_custom_vars: set[str] = set()

        for campaign in campaigns_to_export:
            cid = campaign.get("id")
            if not isinstance(cid, int):
                typer.echo(f"Skipping campaign with invalid id {cid!r}.", err=True)
                continue
            page = 1
            while True:
                raw, _ = client.list_campaign_leads(cid, page=page)
                data = raw.get("data", [])
                if not data:
                    break
                for lead in data:
                    lead_id = lead.get("id")
                    if lead_id is None:
                        continue
                    if lead_id not in lead_campaign_ids:
                        lead_campaign_ids[lead_id] = []
                    lead_campaign_ids[lead_id].append(cid)
                    if lead_id not in all_leads:
                        all_leads[lead_id] = lead
                        for cv in lead.get("custom_variables") or []:
                            if isinstance(cv, dict) and cv.get("name"):
                                all_custom_vars.add(cv["name"])
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1

        typer.echo("Fetching sent email data...", err=True)
        last_sent: dict[int, str] = {}
        for campaign in campaigns_to_export:
            cid = campaign.get("id")
            if not isinstance(cid, int):
                continue
            page = 1
            while True:
                raw, _ = client.list_scheduled_emails(cid, status="sent", page=page)
                items = raw.get("data", [])
                if not items:
                    break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lead_obj = item.get("lead")
                    item_lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
                    sent_at = item.get("sent_at")
                    if isinstance(item_lead_id, int) and isinstance(sent_at, str):
                        existing = last_sent.get(item_lead_id)
                        if existing is None or sent_at > existing:
                            last_sent[item_lead_id] = sent_at
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1

        fixed_fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "title",
            "company",
            "status",
            "emails_sent",
            "opens",
            "replies",
            "tags",
            "last_sent_date",
            "created_at",
            "updated_at",
            "campaign_ids",
        ]
        fixed_fields_set = set(fixed_fields)
        custom_var_fields = sorted(name for name in all_custom_vars if name not in fixed_fields_set)
        fieldnames = fixed_fields + custom_var_fields

        with output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for lead_id, lead in all_leads.items():
                stats = lead.get("overall_stats") or {}
                if not isinstance(stats, dict):
                    stats = {}
                tags_val = ", ".join(
                    t.get("name", "") for t in (lead.get("tags") or []) if isinstance(t, dict)
                )
                cv_map: dict[str, str] = {}
                for cv in lead.get("custom_variables") or []:
                    if isinstance(cv, dict):
                        name = cv.get("name")
                        value = cv.get("value")
                        if isinstance(name, str) and name not in fixed_fields_set:
                            cv_map[name] = str(value) if value is not None else ""
                row: dict[str, Any] = {
                    "id": lead_id,
                    "email": lead.get("email", ""),
                    "first_name": lead.get("first_name", ""),
                    "last_name": lead.get("last_name", ""),
                    "title": lead.get("title", ""),
                    "company": lead.get("company", ""),
                    "status": lead.get("status", ""),
                    "emails_sent": stats.get("emails_sent", ""),
                    "opens": stats.get("opens", ""),
                    "replies": stats.get("replies", ""),
                    "tags": tags_val,
                    "last_sent_date": last_sent.get(lead_id, ""),
                    "created_at": lead.get("created_at", ""),
                    "updated_at": lead.get("updated_at", ""),
                    "campaign_ids": ",".join(str(c) for c in lead_campaign_ids.get(lead_id, [])),
                    **cv_map,
                }
                writer.writerow(row)

        typer.echo(
            f"Exported {len(all_leads)} leads from {len(campaigns_to_export)} campaigns to {output}"
        )

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


@app.command("sync-leads")
def sync_leads(
    ctx: typer.Context,
    campaign_id: int | None = typer.Argument(
        None,
        help="Single campaign ID to sync (omit for --all)",
    ),
    all_campaigns: bool = typer.Option(
        False,
        "--all",
        help="Sync leads from all campaigns.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter campaigns by status (when using --all).",
    ),
    init_schema: bool = typer.Option(
        False,
        "--init",
        help="Initialize database schema before sync.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL (or set PERA_DATABASE_URL).",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """
    Sync EmailBison lead data to pera-contacts database.

    This command:
    1. Fetches campaigns from EmailBison API
    2. For each campaign, fetches all leads
    3. Matches leads to contacts via contactid custom variable
    4. Upserts leads to emailbison_leads table
    5. Updates contacts with EmailBison data (always overwrite)
    6. Upserts campaign memberships with stats

    Examples:
        # Sync single campaign
        emailbison campaign sync-leads 116

        # Sync all campaigns
        emailbison campaign sync-leads --all

        # Initialize schema and sync
        emailbison campaign sync-leads --all --init

        # Filter by campaign status
        emailbison campaign sync-leads --all --status paused
    """
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False

    db_url = (
        database_url
        or os.environ.get("PERA_DATABASE_URL")
        or os.environ.get("BISON_DATABASE_URL")
    )
    if not db_url:
        typer.echo(
            "Database URL required. Set PERA_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not campaign_id and not all_campaigns:
        typer.echo("Provide a campaign ID or use --all to sync all campaigns.", err=True)
        raise typer.Exit(code=2)

    client = client_from_env(base_url=base_url, debug=debug)

    try:
        # Initialize schema if requested
        if init_schema:
            typer.echo("Initializing database schema...", err=True)
            init_db(db_url)
            typer.echo("Schema initialized.", err=True)

        # Determine campaigns to sync
        if all_campaigns:
            typer.echo("Fetching campaigns...", err=True)
            campaigns_data, _ = client.list_all_campaigns(status=status)
            campaigns_to_sync = [
                c for c in campaigns_data
                if isinstance(c, dict) and c.get("total_leads", 0) > 0
            ]
        else:
            raw, _ = client.campaign_details(campaign_id)
            campaign_data = raw.get("data")
            if not isinstance(campaign_data, dict):
                typer.echo(f"Invalid campaign response for id {campaign_id}.", err=True)
                raise typer.Exit(code=3)
            campaigns_to_sync = [campaign_data]

        if not campaigns_to_sync:
            typer.echo("No campaigns with leads found.", err=True)
            raise typer.Exit(code=0)

        typer.echo(f"Syncing {len(campaigns_to_sync)} campaigns...", err=True)

        # Step 1: Upsert campaigns
        campaign_records = []
        for c in campaigns_to_sync:
            campaign_records.append({
                "id": c.get("id"),
                "name": c.get("name", ""),
                "status": c.get("status", "draft"),
                "total_leads": c.get("total_leads", 0),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
            })

        campaign_result = upsert_campaigns(db_url, campaign_records)
        typer.echo(f"  Upserted {campaign_result['campaigns_upserted']} campaigns", err=True)

        # Step 2: Collect leads and build data structures
        all_leads: dict[int, dict[str, Any]] = {}
        contact_campaign_memberships: list[dict[str, Any]] = []

        # Track last_sent_date per (lead_id, campaign_id)
        last_sent: dict[tuple[int, int], str] = {}

        for campaign in campaigns_to_sync:
            cid = campaign.get("id")
            if not isinstance(cid, int):
                typer.echo(f"Skipping campaign with invalid id {cid!r}.", err=True)
                continue

            # Fetch leads (paginated)
            page = 1
            while True:
                raw, _ = client.list_campaign_leads(cid, page=page)
                leads = raw.get("data", [])
                if not leads:
                    break

                for lead in leads:
                    lead_id = lead.get("id")
                    if lead_id is None:
                        continue

                    # Extract contactid from custom_variables
                    contact_id = None
                    contact_data: dict[str, Any] = {}

                    for cv in lead.get("custom_variables") or []:
                        if isinstance(cv, dict):
                            name = cv.get("name", "").lower()
                            value = cv.get("value")
                            if name == "contactid" and value:
                                try:
                                    contact_id = int(value)
                                except (ValueError, TypeError):
                                    pass
                            elif value:
                                contact_data[name] = value

                    # Build lead record
                    if lead_id not in all_leads:
                        all_leads[lead_id] = {
                            "id": lead_id,
                            "contact_id": contact_id,
                            "email": lead.get("email", ""),
                            "first_name": lead.get("first_name"),
                            "last_name": lead.get("last_name"),
                            "title": lead.get("title"),
                            "company": lead.get("company"),
                            "status": lead.get("status", "unverified"),
                            "tags": [
                                t.get("name", "") for t in (lead.get("tags") or [])
                                if isinstance(t, dict)
                            ],
                            "contact_data": contact_data,
                            "created_at": lead.get("created_at"),
                            "updated_at": lead.get("updated_at"),
                        }

                    # Build campaign membership
                    if contact_id:
                        stats = lead.get("overall_stats") or {}
                        if not isinstance(stats, dict):
                            stats = {}

                        contact_campaign_memberships.append({
                            "contact_id": contact_id,
                            "campaign_id": cid,
                            "lead_id": lead_id,
                            "emails_sent": stats.get("emails_sent", 0),
                            "opens": stats.get("opens", 0),
                            "replies": stats.get("replies", 0),
                            "last_sent_date": None,
                        })

                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1

            # Fetch scheduled emails for last_sent_date
            page = 1
            while True:
                raw, _ = client.list_scheduled_emails(cid, status="sent", page=page)
                items = raw.get("data", [])
                if not items:
                    break

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lead_obj = item.get("lead")
                    item_lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
                    sent_at = item.get("sent_at")
                    if isinstance(item_lead_id, int) and isinstance(sent_at, str):
                        key = (item_lead_id, cid)
                        existing = last_sent.get(key)
                        if existing is None or sent_at > existing:
                            last_sent[key] = sent_at

                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1

        # Update last_sent_date in memberships
        for membership in contact_campaign_memberships:
            lead_id = membership["lead_id"]
            campaign_id_key = membership["campaign_id"]
            key = (lead_id, campaign_id_key)
            if key in last_sent:
                membership["last_sent_date"] = last_sent[key]

        # Step 3: Upsert leads
        leads_list = list(all_leads.values())
        leads_result = upsert_leads(db_url, leads_list)
        typer.echo(
            f"  Upserted {leads_result['leads_upserted']} leads "
            f"({leads_result['skipped_no_contactid']} without contactid)",
            err=True,
        )

        # Step 4: Upsert campaign memberships
        membership_result = upsert_contact_campaigns(db_url, contact_campaign_memberships)
        typer.echo(
            f"  Upserted {membership_result['memberships_upserted']} campaign memberships",
            err=True,
        )

        # Summary
        if json_output:
            typer.echo(json.dumps({
                "campaigns": campaign_result,
                "leads": leads_result,
                "memberships": membership_result,
            }, indent=2))
        else:
            typer.echo(
                f"\nSync complete: {campaign_result['campaigns_upserted']} campaigns, "
                f"{leads_result['leads_upserted']} leads, "
                f"{membership_result['memberships_upserted']} memberships"
            )

    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e
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


@app.command("db-stats")
def db_stats(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL (or set PERA_DATABASE_URL).",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show database statistics."""
    db_url = (
        database_url
        or os.environ.get("PERA_DATABASE_URL")
        or os.environ.get("BISON_DATABASE_URL")
    )
    if not db_url:
        typer.echo(
            "Database URL required. Set PERA_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        stats = get_db_stats(db_url)

        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            typer.echo(f"Total campaigns: {stats['total_campaigns']}")
            typer.echo(f"Total leads: {stats['total_leads']}")
            typer.echo(f"Leads with contact: {stats['leads_with_contact']}")
            typer.echo(f"Leads without contact: {stats['leads_without_contact']}")
            typer.echo(f"Total memberships: {stats['total_memberships']}")
            typer.echo("By status:")
            for st, count in stats["by_status"].items():
                typer.echo(f"  {st}: {count}")
            if stats.get("last_sync"):
                typer.echo(f"Last sync: {stats['last_sync']}")
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("campaign-stats")
def campaign_stats_cmd(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show aggregated stats per campaign."""
    db_url = (
        database_url
        or os.environ.get("PERA_DATABASE_URL")
        or os.environ.get("BISON_DATABASE_URL")
    )
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)

    try:
        stats = get_campaign_stats(db_url)

        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            headers = ["ID", "Name", "Status", "Contacts", "Emails", "Opens", "Replies"]
            rows = []
            for s in stats:
                rows.append([
                    str(s["campaign_id"]),
                    s["campaign_name"] or "",
                    s["campaign_status"] or "",
                    str(s["total_contacts"] or 0),
                    str(s["total_emails_sent"] or 0),
                    str(s["total_opens"] or 0),
                    str(s["total_replies"] or 0),
                ])

            for line in _format_table(headers, rows):
                typer.echo(line)

    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("leads-by-status")
def leads_by_status_cmd(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show lead status breakdown per campaign."""
    db_url = (
        database_url
        or os.environ.get("PERA_DATABASE_URL")
        or os.environ.get("BISON_DATABASE_URL")
    )
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)

    try:
        stats = get_leads_by_status_per_campaign(db_url)

        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            headers = ["Campaign ID", "Campaign Name", "Status", "Count"]
            rows = []
            for s in stats:
                rows.append([
                    str(s["campaign_id"]),
                    s["campaign_name"] or "",
                    s["lead_status"] or "",
                    str(s["count"]),
                ])

            for line in _format_table(headers, rows):
                typer.echo(line)

    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("booking-rate")
def booking_rate_cmd(
    ctx: typer.Context,
    state: str = typer.Option("MA", "--state", help="State to filter by."),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show meeting booking rate (reply rate) for campaigns targeting a state."""
    db_url = (
        database_url
        or os.environ.get("PERA_DATABASE_URL")
        or os.environ.get("BISON_DATABASE_URL")
    )
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)

    try:
        result = get_meeting_booking_rate_by_state(db_url, state=state)

        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"Campaigns targeting {state}:")
            typer.echo("")
            headers = ["Campaign ID", "Name", "Contacts", "Replies", "Reply Rate %"]
            rows = []
            for c in result["campaigns"]:
                rows.append([
                    str(c["campaign_id"]),
                    c["campaign_name"] or "",
                    str(c["total_contacts"] or 0),
                    str(c["total_replies"] or 0),
                    str(c["reply_rate_pct"] or 0),
                ])

            for line in _format_table(headers, rows):
                typer.echo(line)

    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e
