from __future__ import annotations

import json
from typing import Any

import typer

from .commands.campaign import app as campaign_app
from .commands.sender_emails import app as sender_emails_app

app = typer.Typer(add_completion=False)
app.add_typer(campaign_app, name="campaign")
app.add_typer(sender_emails_app, name="sender-emails")


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
    debug: bool = typer.Option(False, "--debug", help="Print debug metadata (redacted)."),
) -> None:
    ctx.obj = {"json": json_output, "debug": debug}


def echo_result(data: Any, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
    else:
        typer.echo(data)
