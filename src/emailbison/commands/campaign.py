from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from ..config import ConfigError, load_settings
from ..models import (
    CampaignCreateSpec,
    CampaignSchedule,
    CampaignSettings,
    CreateCampaignResult,
    LeadsSpec,
    SequenceSpec,
)

app = typer.Typer(add_completion=False)


@app.command("create")
def create_campaign(
    ctx: typer.Context,
    file: Path | None = typer.Option(
        None,
        "--file",
        help="Campaign workflow JSON file.",
    ),
    # Core
    name: str | None = typer.Option(None, "--name", help="Campaign name."),
    type: str = typer.Option(
        "outbound",
        "--type",
        help="Campaign type (outbound|reply_followup).",
    ),
    # Leads
    lead_list_id: int | None = typer.Option(
        None,
        "--lead-list-id",
        help="Import leads from existing list id.",
    ),
    lead_id: list[int] | None = typer.Option(
        None,
        "--lead-id",
        help="Import leads by lead id (repeatable).",
    ),
    allow_parallel_sending: bool = typer.Option(
        False,
        "--allow-parallel-sending",
        help="Force add leads that are in-sequence in other campaigns.",
    ),
    # Settings
    max_emails_per_day: int | None = typer.Option(None, "--max-emails-per-day"),
    max_new_leads_per_day: int | None = typer.Option(None, "--max-new-leads-per-day"),
    plain_text: bool | None = typer.Option(
        None,
        "--plain-text/--html",
        help="Send plain text only.",
    ),
    open_tracking: bool | None = typer.Option(None, "--open-tracking/--no-open-tracking"),
    reputation_building: bool | None = typer.Option(
        None,
        "--reputation-building/--no-reputation-building",
    ),
    can_unsubscribe: bool | None = typer.Option(
        None,
        "--can-unsubscribe/--no-can-unsubscribe",
    ),
    unsubscribe_text: str | None = typer.Option(None, "--unsubscribe-text"),
    # Schedule (optional)
    schedule_timezone: str | None = typer.Option(None, "--schedule-timezone"),
    schedule_start: str | None = typer.Option(None, "--schedule-start", help="HH:MM"),
    schedule_end: str | None = typer.Option(None, "--schedule-end", help="HH:MM"),
    include_weekends: bool = typer.Option(False, "--include-weekends"),
    # Sequence steps
    sequence_file: Path | None = typer.Option(
        None,
        "--sequence-file",
        help="JSON file containing {title, sequence_steps}.",
    ),
    # Config overrides
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    try:
        settings = load_settings(base_url=base_url)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e

    if file is not None:
        spec = _validate_spec(_load_json_file(file))
    else:
        if not name:
            typer.echo("Missing --name (or provide --file)", err=True)
            raise typer.Exit(code=2)

        settings_obj = CampaignSettings(
            max_emails_per_day=max_emails_per_day,
            max_new_leads_per_day=max_new_leads_per_day,
            plain_text=plain_text,
            open_tracking=open_tracking,
            reputation_building=reputation_building,
            can_unsubscribe=can_unsubscribe,
            unsubscribe_text=unsubscribe_text,
        )
        if settings_obj.model_dump(exclude_none=True) == {}:
            settings_obj = None

        schedule_obj = None
        if any(v is not None for v in (schedule_timezone, schedule_start, schedule_end)):
            if not (schedule_timezone and schedule_start and schedule_end):
                typer.echo(
                    "If setting schedule, provide --schedule-timezone, "
                    "--schedule-start, and --schedule-end",
                    err=True,
                )
                raise typer.Exit(code=2)
            schedule_obj = CampaignSchedule(
                monday=True,
                tuesday=True,
                wednesday=True,
                thursday=True,
                friday=True,
                saturday=bool(include_weekends),
                sunday=bool(include_weekends),
                start_time=schedule_start,
                end_time=schedule_end,
                timezone=schedule_timezone,
                save_as_template=False,
            )

        leads_obj = None
        if lead_list_id is not None or lead_id:
            leads_obj = LeadsSpec(
                lead_list_id=lead_list_id,
                lead_ids=lead_id or None,
                allow_parallel_sending=allow_parallel_sending,
            )

        sequence_obj = None
        if sequence_file is not None:
            sequence_obj = SequenceSpec.model_validate(_load_json_file(sequence_file))

        spec = CampaignCreateSpec(
            name=name,
            type=type,
            settings=settings_obj,
            schedule=schedule_obj,
            leads=leads_obj,
            sequence=sequence_obj,
        )

    client = EmailBisonClient(settings, debug=debug)
    try:
        created_raw, dbg_create = client.create_campaign(name=spec.name, type=spec.type)
        campaign_id = _extract_id(created_raw)

        if spec.settings is not None:
            client.update_campaign_settings(
                campaign_id,
                spec.settings.model_dump(exclude_none=True),
            )

        if spec.schedule is not None:
            client.create_campaign_schedule(
                campaign_id,
                spec.schedule.model_dump(exclude_none=True),
            )

        if spec.sequence is not None:
            # API expects: {title, sequence_steps: [...]} (exclude None in each step)
            steps = [
                s.model_dump(exclude_none=True) for s in spec.sequence.sequence_steps
            ]
            client.create_sequence_steps_v11(
                campaign_id,
                {"title": spec.sequence.title, "sequence_steps": steps},
            )

        if spec.leads is not None:
            if spec.leads.lead_list_id is not None:
                client.attach_lead_list(
                    campaign_id,
                    {
                        "lead_list_id": spec.leads.lead_list_id,
                        "allow_parallel_sending": spec.leads.allow_parallel_sending,
                    },
                )
            elif spec.leads.lead_ids is not None:
                client.attach_leads(
                    campaign_id,
                    {
                        "lead_ids": spec.leads.lead_ids,
                        "allow_parallel_sending": spec.leads.allow_parallel_sending,
                    },
                )

        result = CreateCampaignResult(
            id=campaign_id,
            name=spec.name,
            status=_extract_status(created_raw),
            raw=created_raw,
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
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        raise typer.Exit(code=5) from e
    finally:
        client.close()

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    typer.echo(f"id={result.id} name={result.name} status={result.status or 'unknown'}")

    if debug:
        typer.echo(
            f"debug: method={dbg_create.method} status={dbg_create.status_code} "
            f"url={dbg_create.url}",
            err=True,
        )
        typer.echo(
            f"debug: auth={client.debug_redacted_headers()['Authorization']}",
            err=True,
        )
        if dbg_create.request_id:
            typer.echo(f"debug: request_id={dbg_create.request_id}", err=True)


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(code=2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid JSON in {path}: {e}", err=True)
        raise typer.Exit(code=2) from e
    if not isinstance(data, dict):
        typer.echo("Campaign file must contain a JSON object at the top level", err=True)
        raise typer.Exit(code=2)
    return data


def _validate_spec(data: dict[str, Any]) -> CampaignCreateSpec:
    try:
        return CampaignCreateSpec.model_validate(data)
    except Exception as e:
        typer.echo(f"Validation error: {e}", err=True)
        raise typer.Exit(code=2) from e


def _extract_id(raw: dict[str, Any]) -> int:
    data = raw.get("data")
    if isinstance(data, dict) and isinstance(data.get("id"), int):
        return int(data["id"])
    raise ValueError(f"Could not extract campaign id from response: {raw}")


def _extract_status(raw: dict[str, Any]) -> str | None:
    data = raw.get("data")
    if isinstance(data, dict) and isinstance(data.get("status"), str):
        return data.get("status")
    return None
