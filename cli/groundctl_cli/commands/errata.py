"""groundctl errata list|show|affected-servers

Maps to /errata/*.
"""

from __future__ import annotations

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_errata(
    ctx: typer.Context,
    source: str = typer.Option(None, "--source", help="usn | dsa"),
    cve: str = typer.Option(None, "--cve"),
    published_since: str = typer.Option(None, "--published-since", help="ISO 8601 datetime."),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List security errata."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/errata",
            params={
                "source": source,
                "cve": cve,
                "published_since": published_since,
                "limit": limit,
                "offset": offset,
            },
        )
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    advisory_id: str = typer.Argument(..., help="e.g. USN-1234-1 or DSA-5678-1."),
) -> None:
    """Show a single erratum."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/errata/{advisory_id}")
    render_item(response.json(), output=output)


@app.command("affected-servers")
def affected_servers(
    ctx: typer.Context,
    advisory_id: str = typer.Argument(...),
) -> None:
    """List servers whose installed package versions are older than this
    advisory's fixed versions."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/errata/{advisory_id}/affected-servers")
    render_item(response.json(), output=output)
