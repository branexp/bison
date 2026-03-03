from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import EmailBisonClient
from ..config import ConfigError, load_settings


__all__ = ["client_from_env", "dump_or_human", "load_json_file"]


def client_from_env(*, base_url: str | None, debug: bool) -> EmailBisonClient:
    try:
        settings = load_settings(base_url=base_url)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    return EmailBisonClient(settings, debug=debug)


def dump_or_human(
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


def load_json_file(path: Path) -> dict[str, Any]:
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
