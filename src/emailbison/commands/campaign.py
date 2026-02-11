from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
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
    WorkflowStepResult,
)

# Additional campaign lifecycle + management commands
from .campaign_admin import (
    archive_campaign as _archive_campaign,
)
from .campaign_admin import (
    attach_sender_emails as _attach_sender_emails,
)
from .campaign_admin import (
    campaign_replies as _campaign_replies,
)
from .campaign_admin import (
    campaign_sender_emails as _campaign_sender_emails,
)
from .campaign_admin import (
    campaign_stats as _campaign_stats,
)
from .campaign_admin import (
    campaign_summary as _campaign_summary,
)
from .campaign_admin import (
    get_campaign as _get_campaign,
)
from .campaign_admin import (
    list_campaigns as _list_campaigns,
)
from .campaign_admin import (
    pause_campaign as _pause_campaign,
)
from .campaign_admin import (
    remove_sender_emails as _remove_sender_emails,
)
from .campaign_admin import (
    resume_campaign as _resume_campaign,
)
from .campaign_admin import (
    start_campaign as _start_campaign,
)
from .campaign_admin import (
    stop_future_emails as _stop_future_emails,
)
from .campaign_sequence import app as campaign_sequence_app

app = typer.Typer(add_completion=False)


class WorkflowValidationError(RuntimeError):
    pass


LEAD_LIST_PENDING_STATUSES = {"unprocessed", "processing", "pending", "queued"}
LEAD_LIST_FAILED_STATUSES = {"failed", "error"}
LEAD_LIST_POLL_INTERVAL_SECONDS = 2.0
LEAD_LIST_POLL_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class BatchFilePlan:
    path: Path
    campaign_name: str
    lead_count: int
    columns_to_map: dict[str, str]


# Register lifecycle/management commands into the same `campaign` group.
app.command("list")(_list_campaigns)
app.command("get")(_get_campaign)
app.command("pause")(_pause_campaign)
app.command("resume")(_resume_campaign)
app.command("start")(_start_campaign)
app.command("archive")(_archive_campaign)

app.command("sender-emails")(_campaign_sender_emails)
app.command("attach-sender-emails")(_attach_sender_emails)
app.command("remove-sender-emails")(_remove_sender_emails)

app.command("stats")(_campaign_stats)
app.command("summary")(_campaign_summary)
app.command("replies")(_campaign_replies)
app.command("stop-future-emails")(_stop_future_emails)

# Nested sequence management group
app.add_typer(campaign_sequence_app, name="sequence")


def _load_settings_or_exit(*, base_url: str | None) -> Any:
    try:
        return load_settings(base_url=base_url)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e


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
    # Sender emails
    sender_email_id: list[int] | None = typer.Option(
        None,
        "--sender-email-id",
        help="Attach sender email id (repeatable).",
    ),
    # Behavior
    start: bool = typer.Option(
        False,
        "--start",
        help="Attempt to start sending after provisioning (resume).",
    ),
    force_start: bool = typer.Option(
        False,
        "--force-start",
        help="Skip preflight checks when starting.",
    ),
    # Config overrides
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    settings = _load_settings_or_exit(base_url=base_url)

    if file is not None:
        spec = _validate_spec(_load_json_file(file))
        if start:
            spec = spec.model_copy(update={"start": True})
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
            sender_email_ids=sender_email_id or None,
            start=start,
        )

    steps: list[WorkflowStepResult] = []
    campaign_id: int | None = None
    sender_email_ids_attached: list[int] | None = None
    sequence_id: int | None = None
    sequence_step_ids: list[int] | None = None

    client = EmailBisonClient(settings, debug=debug)
    try:
        created_raw, dbg_create = client.create_campaign(name=spec.name, type=spec.type)
        campaign_id = _extract_id(created_raw)
        steps.append(
            WorkflowStepResult(
                name="campaign.create",
                method=dbg_create.method,
                url=dbg_create.url,
                status_code=dbg_create.status_code,
                request_id=dbg_create.request_id,
            )
        )

        if spec.settings is not None:
            _, dbg = client.update_campaign_settings(
                campaign_id,
                spec.settings.model_dump(exclude_none=True),
            )
            steps.append(
                WorkflowStepResult(
                    name="campaign.update_settings",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

        if spec.schedule is not None:
            _, dbg = client.create_campaign_schedule(
                campaign_id,
                spec.schedule.model_dump(exclude_none=True),
            )
            steps.append(
                WorkflowStepResult(
                    name="campaign.schedule",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

        if spec.sequence is not None:
            # API expects: {title, sequence_steps: [...]} (exclude None in each step)
            seq_steps = [s.model_dump(exclude_none=True) for s in spec.sequence.sequence_steps]
            seq_raw, dbg = client.create_sequence_steps_v11(
                campaign_id,
                {"title": spec.sequence.title, "sequence_steps": seq_steps},
            )
            steps.append(
                WorkflowStepResult(
                    name="campaign.sequence.create",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

            data = seq_raw.get("data")
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                sequence_id = int(data["id"])
            if isinstance(data, dict) and isinstance(data.get("sequence_steps"), list):
                ids: list[int] = []
                for row in data["sequence_steps"]:
                    if isinstance(row, dict) and isinstance(row.get("id"), int):
                        ids.append(int(row["id"]))
                sequence_step_ids = ids or None

        sender_ids_to_attach: list[int] | None = None
        if spec.sender_email_ids is not None:
            sender_ids_to_attach = spec.sender_email_ids
        elif spec.sender_emails is not None:
            raw_sender, dbg = client.list_sender_emails(
                search=spec.sender_emails.search,
                tag_ids=spec.sender_emails.tag_ids,
                excluded_tag_ids=spec.sender_emails.excluded_tag_ids,
                without_tags=spec.sender_emails.without_tags,
            )
            steps.append(
                WorkflowStepResult(
                    name="sender_emails.list",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

            data = raw_sender.get("data")
            candidates: list[dict[str, Any]] = []
            if isinstance(data, list):
                for row in data:
                    if not isinstance(row, dict):
                        continue
                    if not isinstance(row.get("id"), int):
                        continue
                    if spec.sender_emails.status is not None:
                        if str(row.get("status")) != str(spec.sender_emails.status):
                            continue
                    candidates.append(row)

            candidates.sort(key=lambda r: int(r["id"]))
            sender_ids_to_attach = [
                int(r["id"]) for r in candidates[: int(spec.sender_emails.limit)]
            ]
            if not sender_ids_to_attach:
                raise WorkflowValidationError(
                    "No sender emails matched sender_emails selector. "
                    "Try `emailbison sender-emails list` to inspect available accounts."
                )

        if sender_ids_to_attach:
            _, dbg = client.attach_sender_emails(
                campaign_id,
                sender_email_ids=sender_ids_to_attach,
            )
            steps.append(
                WorkflowStepResult(
                    name="campaign.attach_sender_emails",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )
            sender_email_ids_attached = sender_ids_to_attach

        if spec.leads is not None:
            if spec.leads.lead_list_id is not None:
                _, dbg = client.attach_lead_list(
                    campaign_id,
                    {
                        "lead_list_id": spec.leads.lead_list_id,
                        "allow_parallel_sending": spec.leads.allow_parallel_sending,
                    },
                )
                steps.append(
                    WorkflowStepResult(
                        name="campaign.attach_lead_list",
                        method=dbg.method,
                        url=dbg.url,
                        status_code=dbg.status_code,
                        request_id=dbg.request_id,
                    )
                )
            elif spec.leads.lead_ids is not None:
                _, dbg = client.attach_leads(
                    campaign_id,
                    {
                        "lead_ids": spec.leads.lead_ids,
                        "allow_parallel_sending": spec.leads.allow_parallel_sending,
                    },
                )
                steps.append(
                    WorkflowStepResult(
                        name="campaign.attach_leads",
                        method=dbg.method,
                        url=dbg.url,
                        status_code=dbg.status_code,
                        request_id=dbg.request_id,
                    )
                )

        started = False
        start_status: str | None = None
        if spec.start:
            missing: list[str] = []

            details_raw, dbg = client.campaign_details(campaign_id)
            steps.append(
                WorkflowStepResult(
                    name="campaign.details",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

            data = details_raw.get("data")
            total_leads = None
            if isinstance(data, dict) and isinstance(data.get("total_leads"), int):
                total_leads = int(data.get("total_leads"))
            if not total_leads:
                missing.append("no leads attached")

            senders_raw, dbg = client.get_campaign_sender_emails(campaign_id)
            steps.append(
                WorkflowStepResult(
                    name="campaign.sender_emails",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )
            senders = senders_raw.get("data")
            if not isinstance(senders, list) or len(senders) == 0:
                missing.append("no sender emails attached")

            seq_raw, dbg = client.get_sequence_steps_v11(campaign_id)
            steps.append(
                WorkflowStepResult(
                    name="campaign.sequence.get",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )
            seq_data = seq_raw.get("data")
            seq_steps_data = None
            if isinstance(seq_data, dict):
                seq_steps_data = seq_data.get("sequence_steps")
            if not isinstance(seq_steps_data, list) or len(seq_steps_data) == 0:
                missing.append("no sequence steps")

            if missing and not force_start:
                raise WorkflowValidationError(
                    "Refusing to start campaign (preflight failed): " + ", ".join(missing)
                )

            _, dbg = client.resume_campaign(campaign_id)
            steps.append(
                WorkflowStepResult(
                    name="campaign.resume",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )

            details_raw2, dbg = client.campaign_details(campaign_id)
            steps.append(
                WorkflowStepResult(
                    name="campaign.details_after_start",
                    method=dbg.method,
                    url=dbg.url,
                    status_code=dbg.status_code,
                    request_id=dbg.request_id,
                )
            )
            start_status = _extract_status(details_raw2)
            started = True

        result = CreateCampaignResult(
            id=campaign_id,
            name=spec.name,
            status=_extract_status(created_raw),
            sender_email_ids=sender_email_ids_attached,
            sequence_id=sequence_id,
            sequence_step_ids=sequence_step_ids,
            started=started,
            start_status=start_status,
            steps=steps,
            raw=created_raw,
        )

    except WorkflowValidationError as e:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "error": {
                            "type": type(e).__name__,
                            "message": str(e),
                        },
                        "campaign_id": campaign_id,
                        "steps": [s.model_dump() for s in steps],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e
    except AuthError as e:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "error": {"type": type(e).__name__, "message": str(e)},
                        "campaign_id": campaign_id,
                        "steps": [s.model_dump() for s in steps],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "error": {"type": type(e).__name__, "message": str(e)},
                        "campaign_id": campaign_id,
                        "steps": [s.model_dump() for s in steps],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "error": {
                            "type": type(e).__name__,
                            "message": str(e),
                            "status_code": e.status_code,
                            "details": e.details,
                        },
                        "campaign_id": campaign_id,
                        "steps": [s.model_dump() for s in steps],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "error": {"type": type(e).__name__, "message": str(e)},
                        "campaign_id": campaign_id,
                        "steps": [s.model_dump() for s in steps],
                    },
                    indent=2,
                )
            )
        else:
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


@app.command("create-batch")
def create_batch_campaigns(
    ctx: typer.Context,
    dir: Path = typer.Option(
        ...,
        "--dir",
        help="Directory containing district-segmented CSV files.",
    ),
    sequence_file: Path | None = typer.Option(
        None,
        "--sequence-file",
        help="JSON file containing {title, sequence_steps}.",
    ),
    sender_email_id: list[int] | None = typer.Option(
        None,
        "--sender-email-id",
        help="Attach sender email id (repeatable).",
    ),
    settings_file: Path | None = typer.Option(
        None,
        "--settings-file",
        help="JSON file containing campaign settings payload.",
    ),
    schedule_file: Path | None = typer.Option(
        None,
        "--schedule-file",
        help="JSON file containing campaign schedule payload.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without API calls."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    if not dir.exists() or not dir.is_dir():
        typer.echo(f"Directory not found: {dir}", err=True)
        raise typer.Exit(code=2)

    try:
        settings_obj: CampaignSettings | None = None
        if settings_file is not None:
            settings_obj = CampaignSettings.model_validate(_load_json_file(settings_file))

        schedule_obj: CampaignSchedule | None = None
        if schedule_file is not None:
            schedule_obj = CampaignSchedule.model_validate(_load_json_file(schedule_file))

        sequence_obj: SequenceSpec | None = None
        if sequence_file is not None:
            sequence_obj = SequenceSpec.model_validate(_load_json_file(sequence_file))

        if not dry_run and not sender_email_id:
            raise WorkflowValidationError(
                "Missing --sender-email-id (repeatable) unless --dry-run is used."
            )

        plans: list[BatchFilePlan] = _build_batch_plans(dir)
        if not plans:
            raise WorkflowValidationError(f"No CSV files found in {dir}")
    except WorkflowValidationError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e
    except Exception as e:
        typer.echo(f"Validation error: {e}", err=True)
        raise typer.Exit(code=2) from e

    if dry_run:
        payload = {
            "dry_run": True,
            "summary": {
                "total_processed": len(plans),
                "succeeded": len(plans),
                "failed": 0,
                "leads_loaded": sum(p.lead_count for p in plans),
            },
            "files": [
                {
                    "csv": str(p.path),
                    "campaign_name": p.campaign_name,
                    "lead_count": p.lead_count,
                }
                for p in plans
            ],
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            for p in plans:
                typer.echo(
                    f"[DRY-RUN] csv={p.path.name} campaign={p.campaign_name} leads={p.lead_count}"
                )
            typer.echo(
                "summary: total_processed={total_processed} succeeded={succeeded} "
                "failed={failed} leads_loaded={leads_loaded}".format(**payload["summary"])
            )
        return

    settings = _load_settings_or_exit(base_url=base_url)
    client = EmailBisonClient(settings, debug=debug)

    total_processed = 0
    succeeded = 0
    failed = 0
    leads_loaded = 0
    file_results: list[dict[str, Any]] = []

    try:
        for plan in plans:
            total_processed += 1
            try:
                upload_raw, _ = client.upload_leads_csv(
                    name=plan.campaign_name,
                    csv_path=plan.path,
                    columns_to_map=plan.columns_to_map,
                )
                lead_list_id, initial_status = _extract_lead_list_info(upload_raw)
                lead_list_status = _wait_for_lead_list_processing(
                    client=client,
                    lead_list_id=lead_list_id,
                    initial_status=initial_status,
                )

                created_raw, _ = client.create_campaign(name=plan.campaign_name, type="outbound")
                campaign_id = _extract_id(created_raw)

                if settings_obj is not None:
                    client.update_campaign_settings(
                        campaign_id,
                        settings_obj.model_dump(exclude_none=True),
                    )
                if schedule_obj is not None:
                    client.create_campaign_schedule(
                        campaign_id,
                        schedule_obj.model_dump(exclude_none=True),
                    )
                if sequence_obj is not None:
                    seq_steps = [
                        s.model_dump(exclude_none=True) for s in sequence_obj.sequence_steps
                    ]
                    client.create_sequence_steps_v11(
                        campaign_id,
                        {"title": sequence_obj.title, "sequence_steps": seq_steps},
                    )
                if sender_email_id:
                    client.attach_sender_emails(
                        campaign_id,
                        sender_email_ids=sender_email_id,
                    )

                client.attach_lead_list(
                    campaign_id,
                    {"lead_list_id": lead_list_id, "allow_parallel_sending": False},
                )

                succeeded += 1
                leads_loaded += plan.lead_count
                file_results.append(
                    {
                        "csv": str(plan.path),
                        "campaign_name": plan.campaign_name,
                        "campaign_id": campaign_id,
                        "lead_list_id": lead_list_id,
                        "lead_list_status": lead_list_status,
                        "lead_count": plan.lead_count,
                        "ok": True,
                    }
                )
                if not json_output:
                    typer.echo(
                        f"ok csv={plan.path.name} campaign_id={campaign_id} "
                        f"lead_list_id={lead_list_id} leads={plan.lead_count}"
                    )
            except (ApiError, AuthError, NetworkError, ValueError, WorkflowValidationError) as e:
                failed += 1
                file_results.append(
                    {
                        "csv": str(plan.path),
                        "campaign_name": plan.campaign_name,
                        "lead_count": plan.lead_count,
                        "ok": False,
                        "error_type": type(e).__name__,
                        "error": str(e),
                    }
                )
                if not json_output:
                    typer.echo(f"error csv={plan.path.name}: {e}", err=True)
                continue
    finally:
        client.close()

    summary = {
        "total_processed": total_processed,
        "succeeded": succeeded,
        "failed": failed,
        "leads_loaded": leads_loaded,
    }
    payload = {"summary": summary, "files": file_results}

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(
            "summary: total_processed={total_processed} succeeded={succeeded} "
            "failed={failed} leads_loaded={leads_loaded}".format(**summary)
        )


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


def _build_batch_plans(dir_path: Path) -> list[BatchFilePlan]:
    plans: list[BatchFilePlan] = []
    for csv_path in sorted(dir_path.glob("*.csv")):
        plans.append(_build_batch_plan(csv_path))
    return plans


def _build_batch_plan(csv_path: Path) -> BatchFilePlan:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise WorkflowValidationError(f"CSV has no header row: {csv_path}")

        first_name_col = _pick_csv_column(
            reader.fieldnames,
            ["first_name", "first name", "firstname", "first"],
        )
        last_name_col = _pick_csv_column(
            reader.fieldnames,
            ["last_name", "last name", "lastname", "last"],
        )
        email_col = _pick_csv_column(
            reader.fieldnames,
            ["email", "email_address", "email address", "emailwork"],
        )
        if first_name_col is None or last_name_col is None or email_col is None:
            raise WorkflowValidationError(
                f"CSV missing required columns (first_name,last_name,email): {csv_path}"
            )

        lead_count = 0
        district_name: str | None = None
        for row in reader:
            if not isinstance(row, dict):
                continue
            if any(str(v).strip() for v in row.values() if v is not None):
                lead_count += 1
            if district_name is None:
                district_name = _extract_district_name_from_row(row)

    campaign_name = district_name or _campaign_name_from_path(csv_path)
    if lead_count <= 0:
        raise WorkflowValidationError(f"CSV contains no lead rows: {csv_path}")

    return BatchFilePlan(
        path=csv_path,
        campaign_name=campaign_name,
        lead_count=lead_count,
        columns_to_map={
            "first_name": first_name_col,
            "last_name": last_name_col,
            "email": email_col,
        },
    )


def _pick_csv_column(fieldnames: list[str], aliases: list[str]) -> str | None:
    normalized_map = {name.strip().lower(): name for name in fieldnames}
    for alias in aliases:
        chosen = normalized_map.get(alias.strip().lower())
        if chosen:
            return chosen
    return None


def _extract_district_name_from_row(row: dict[str, Any]) -> str | None:
    keys = {
        "district",
        "district_name",
        "districtname",
        "district name",
        "company",
        "organization",
    }
    for key, value in row.items():
        if value is None:
            continue
        if str(key).strip().lower() in keys:
            cleaned = str(value).strip()
            if cleaned:
                return cleaned
    return None


def _campaign_name_from_path(csv_path: Path) -> str:
    stem = csv_path.stem.replace("_", " ").replace("-", " ").strip()
    return stem or csv_path.name


def _extract_lead_list_info(raw: dict[str, Any]) -> tuple[int, str | None]:
    candidates: list[dict[str, Any]] = []
    data = raw.get("data")
    if isinstance(data, dict):
        candidates.append(data)
        lead_list = data.get("lead_list")
        if isinstance(lead_list, dict):
            candidates.append(lead_list)
    lead_list_top = raw.get("lead_list")
    if isinstance(lead_list_top, dict):
        candidates.append(lead_list_top)
    candidates.append(raw)

    lead_list_id: int | None = None
    status: str | None = None
    for candidate in candidates:
        if lead_list_id is None:
            lead_list_id = _coerce_int(candidate.get("lead_list_id"))
        if lead_list_id is None:
            lead_list_id = _coerce_int(candidate.get("id"))
        if status is None and isinstance(candidate.get("status"), str):
            status = str(candidate.get("status"))
        if lead_list_id is not None and status is not None:
            break

    if lead_list_id is None:
        raise ValueError(f"Could not extract lead list id from response: {raw}")
    return lead_list_id, status


def _extract_lead_list_status(raw: dict[str, Any]) -> str | None:
    candidates: list[dict[str, Any]] = []
    data = raw.get("data")
    if isinstance(data, dict):
        candidates.append(data)
        lead_list = data.get("lead_list")
        if isinstance(lead_list, dict):
            candidates.append(lead_list)
    candidates.append(raw)

    for candidate in candidates:
        status = candidate.get("status")
        if isinstance(status, str):
            return status
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        parsed = value.strip()
        if parsed.isdigit():
            return int(parsed)
    return None


def _wait_for_lead_list_processing(
    *,
    client: EmailBisonClient,
    lead_list_id: int,
    initial_status: str | None,
) -> str:
    status = initial_status
    if status and status.strip().lower() in LEAD_LIST_FAILED_STATUSES:
        raise WorkflowValidationError(f"Lead list {lead_list_id} failed immediately: {status}")
    if status and status.strip().lower() not in LEAD_LIST_PENDING_STATUSES:
        return status

    start = time.monotonic()
    while (time.monotonic() - start) <= LEAD_LIST_POLL_TIMEOUT_SECONDS:
        raw, _ = client.get_lead_list(lead_list_id)
        status = _extract_lead_list_status(raw)
        if status is None:
            time.sleep(LEAD_LIST_POLL_INTERVAL_SECONDS)
            continue
        normalized = status.strip().lower()
        if normalized in LEAD_LIST_FAILED_STATUSES:
            raise WorkflowValidationError(f"Lead list {lead_list_id} processing failed: {status}")
        if normalized not in LEAD_LIST_PENDING_STATUSES:
            return status
        time.sleep(LEAD_LIST_POLL_INTERVAL_SECONDS)

    raise WorkflowValidationError(
        f"Timed out waiting for lead list {lead_list_id} to finish processing."
    )
