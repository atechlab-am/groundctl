"""groundctl server register|list|show|decommission|assign-site

Maps to /servers/*. "register" here maps to POST /servers (admin/operator-
initiated registration) — distinct from the token-based self-registration
flow under /enrollment, which isn't a CLI-driven action.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def register(
    ctx: typer.Context,
    hostname: str = typer.Option(..., "--hostname"),
    ip_address: str = typer.Option(..., "--ip-address"),
    ssh_user: str = typer.Option(..., "--ssh-user"),
    environment_id: uuid.UUID = typer.Option(..., "--environment-id"),
    site_id: uuid.UUID = typer.Option(None, "--site-id"),
) -> None:
    """Register a new server (content host)."""
    output = get_output(ctx)
    payload = {
        "hostname": hostname,
        "ip_address": ip_address,
        "ssh_user": ssh_user,
        "environment_id": str(environment_id),
        "site_id": str(site_id) if site_id else None,
    }
    with authed_client() as client:
        response = client.post("/servers", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_servers(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Option(None, "--environment-id"),
    host_group_id: uuid.UUID = typer.Option(None, "--host-group-id"),
    site_id: uuid.UUID = typer.Option(None, "--site-id"),
    lifecycle_state: str = typer.Option(None, "--lifecycle-state", help="active | decommissioned"),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List servers."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/servers",
            params={
                "environment_id": str(environment_id) if environment_id else None,
                "host_group_id": str(host_group_id) if host_group_id else None,
                "site_id": str(site_id) if site_id else None,
                "lifecycle_state": lifecycle_state,
                "limit": limit,
                "offset": offset,
            },
        )
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
    facts: bool = typer.Option(False, "--facts", help="Show the latest gathered facts instead of the server record."),
    facts_history: bool = typer.Option(
        False, "--facts-history", help="Show the full facts history instead of the server record."
    ),
    limit: int = typer.Option(100, "--limit", help="Only used with --facts-history."),
    offset: int = typer.Option(0, "--offset", help="Only used with --facts-history."),
) -> None:
    """Show a server's record, latest facts, or facts history."""
    output = get_output(ctx)
    with authed_client() as client:
        if facts_history:
            response = client.get(f"/servers/{server_id}/facts/history", params={"limit": limit, "offset": offset})
            render_list(response.json(), output=output)
            return
        if facts:
            response = client.get(f"/servers/{server_id}/facts")
        else:
            response = client.get(f"/servers/{server_id}")
    render_item(response.json(), output=output)


@app.command()
def decommission(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Mark a server as decommissioned."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/servers/{server_id}/decommission")
    render_item(response.json(), output=output)


@app.command("assign-site")
def assign_site(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
    site_id: uuid.UUID = typer.Option(None, "--site-id", help="Omit to unassign the server from any site."),
) -> None:
    """Assign (or clear, if --site-id is omitted) a server's site."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(
            f"/servers/{server_id}/assign-site",
            params={"site_id": str(site_id) if site_id else None},
        )
    render_item(response.json(), output=output)
