from __future__ import annotations

import json
from pathlib import Path

import typer

from ..client import ApiError, AuthError, NetworkError
from ..models import SequenceSpec, SequenceUpdateSpec
from ._shared import client_from_env, dump_or_human, load_json_file

app = typer.Typer(add_completion=False)


@app.command("get")
def sequence_get(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Get the sequence steps for a campaign (v1.1)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        raw, _ = client.get_sequence_steps_v11(campaign_id)

        lines: list[str] = []
        data = raw.get("data")
        if isinstance(data, dict):
            seq_id = data.get("sequence_id")
            if seq_id is not None:
                lines.append(f"sequence_id={seq_id}")

            steps = data.get("sequence_steps")
            if isinstance(steps, list):
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    sid = step.get("id")
                    order = step.get("order")
                    wait = step.get("wait_in_days")
                    subj = step.get("email_subject")
                    lines.append(f"step_id={sid} order={order} wait_in_days={wait} subject={subj}")

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


@app.command("set")
def sequence_set(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    file: Path = typer.Option(..., "--file", help="JSON file containing {title, sequence_steps}."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Create sequence steps from scratch for a campaign (v1.1)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    spec = SequenceSpec.model_validate(load_json_file(file))

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        steps = [s.model_dump(exclude_none=True) for s in spec.sequence_steps]
        raw, _ = client.create_sequence_steps_v11(
            campaign_id,
            {"title": spec.title, "sequence_steps": steps},
        )
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


@app.command("update")
def sequence_update(
    ctx: typer.Context,
    sequence_id: int = typer.Argument(..., help="Sequence id (see `sequence get`)."),
    file: Path = typer.Option(
        ..., "--file", help="JSON file containing {title, sequence_steps:[{id,...}]}."
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Update an existing sequence (v1.1)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    spec = SequenceUpdateSpec.model_validate(load_json_file(file))

    client = client_from_env(base_url=base_url, debug=debug)
    try:
        steps = [s.model_dump(exclude_none=True) for s in spec.sequence_steps]
        raw, _ = client.update_sequence_steps_v11(
            sequence_id,
            {"title": spec.title, "sequence_steps": steps},
        )
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
