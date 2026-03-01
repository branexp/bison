from __future__ import annotations

import typer
from rich.console import Console

from ..client import EmailBisonClient
from ..config import ConfigError, load_settings

_err = Console(stderr=True)


def client_from_env(*, base_url: str | None, debug: bool) -> EmailBisonClient:
    """Create an EmailBisonClient from environment/config, or exit on error."""
    try:
        settings = load_settings(base_url=base_url)
    except ConfigError as e:
        _err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=3) from e
    return EmailBisonClient(settings, debug=debug)
