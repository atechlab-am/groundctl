"""groundctl compliance check|search

Maps to POST /compliance/servers/{server_id}/check and
GET /compliance/packages/search.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def check(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(..., help="Server to check drift for."),
) -> None:
    """Compute package drift for a server against its environment's
    currently-published content view version. Requires gather-facts to have
    run at least once."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/compliance/servers/{server_id}/check")
    render_item(response.json(), output=output)


@app.command()
def search(
    ctx: typer.Context,
    package_name: str = typer.Option(..., "--package-name"),
    operator: str = typer.Option(None, "--operator", help="lt|le|eq|ge|gt (requires --compare-version)."),
    compare_version: str = typer.Option(None, "--compare-version"),
) -> None:
    """Find which servers have a package installed, optionally filtered by
    a Debian version comparison (e.g. openssl < 3.0.0-1)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/compliance/packages/search",
            params={"package_name": package_name, "operator": operator, "compare_version": compare_version},
        )
    render_item(response.json(), output=output)
