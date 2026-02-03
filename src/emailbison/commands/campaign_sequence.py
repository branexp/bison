from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import ApiError, AuthError, EmailBisonClient, NetworkError
from ..config import ConfigError, load_settings
from ..models import SequenceSpec, SequenceUpdateSpec

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
        typer.echo("File must contain a JSON object at the top level", err=True)
        raise typer.Exit(code=2)
    return data


@app.command("get")
def sequence_get(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Get the sequence steps for a campaign (v1.1)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
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


@app.command("set")
def sequence_set(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(...),
    file: Path = typer.Option(
        ..., "--file", help="JSON file containing {title, sequence_steps}."
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """Create sequence steps from scratch for a campaign (v1.1)."""

    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    spec = SequenceSpec.model_validate(_load_json_file(file))

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        steps = [s.model_dump(exclude_none=True) for s in spec.sequence_steps]
        raw, _ = client.create_sequence_steps_v11(
            campaign_id,
            {"title": spec.title, "sequence_steps": steps},
        )
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

    spec = SequenceUpdateSpec.model_validate(_load_json_file(file))

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        steps = [s.model_dump(exclude_none=True) for s in spec.sequence_steps]
        raw, _ = client.update_sequence_steps_v11(
            sequence_id,
            {"title": spec.title, "sequence_steps": steps},
        )
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
