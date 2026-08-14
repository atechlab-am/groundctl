"""groundctl site create|list|show|set-relay|set-environments

Maps to /sites/*. "set-relay" maps to POST /sites/{id}/relay (a site has at
most one relay — 409 if one already exists). "show --relay" and
"show --environments" surface the sub-resources since the site record
itself doesn't embed them.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    description: str = typer.Option(None, "--description"),
) -> None:
    """Create a site."""
    output = get_output(ctx)
    payload = {"name": name, "description": description}
    with authed_client() as client:
        response = client.post("/sites", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_sites(
    ctx: typer.Context,
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List sites."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get("/sites", params={"limit": limit, "offset": offset})
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    site_id: uuid.UUID = typer.Argument(...),
    relay: bool = typer.Option(False, "--relay", help="Show this site's relay instead of the site record."),
    environments: bool = typer.Option(
        False, "--environments", help="Show this site's assigned environments instead of the site record."
    ),
    limit: int = typer.Option(100, "--limit", help="Only used with --environments."),
    offset: int = typer.Option(0, "--offset", help="Only used with --environments."),
) -> None:
    """Show a site, its relay (--relay), or its assigned environments (--environments)."""
    output = get_output(ctx)
    with authed_client() as client:
        if relay:
            response = client.get(f"/sites/{site_id}/relay")
            render_item(response.json(), output=output)
            return
        if environments:
            response = client.get(f"/sites/{site_id}/environments", params={"limit": limit, "offset": offset})
            render_list(response.json(), output=output)
            return
        response = client.get(f"/sites/{site_id}")
    render_item(response.json(), output=output)


@app.command("set-relay")
def set_relay(
    ctx: typer.Context,
    site_id: uuid.UUID = typer.Argument(...),
    hostname: str = typer.Option(..., "--hostname"),
    ssh_user: str = typer.Option(..., "--ssh-user"),
) -> None:
    """Create this site's relay. A site can have at most one — this fails
    with a conflict if one already exists (no update endpoint on the
    backend)."""
    output = get_output(ctx)
    payload = {"hostname": hostname, "ssh_user": ssh_user}
    with authed_client() as client:
        response = client.post(f"/sites/{site_id}/relay", json=payload)
    render_item(response.json(), output=output)


@app.command("set-environments")
def set_environments(
    ctx: typer.Context,
    site_id: uuid.UUID = typer.Argument(...),
    environment_id: list[uuid.UUID] = typer.Option(
        None, "--environment-id", help="Repeatable. Replaces the full assigned-environments list; omit entirely to clear it."
    ),
) -> None:
    """Replace the full set of environments assigned to this site."""
    output = get_output(ctx)
    payload = {"environment_ids": [str(e) for e in environment_id] if environment_id else []}
    with authed_client() as client:
        response = client.put(f"/sites/{site_id}/environments", json=payload)
    render_list(response.json(), output=output)
