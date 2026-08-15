"""groundctl server register|list|show|decommission|assign-site|
assign-environment|beacon-state|beacon-token issue/list/revoke

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


@app.command("assign-environment")
def assign_environment(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
    environment_id: uuid.UUID = typer.Option(..., "--environment-id"),
    reason: str = typer.Option(None, "--reason"),
) -> None:
    """Reassign a server's lifecycle environment. Doesn't move any
    packages by itself — the host picks up the new apt source on its
    next bootstrap (`groundctl job trigger-bootstrap`) or beacon checkin."""
    output = get_output(ctx)
    payload = {"environment_id": str(environment_id), "reason": reason}
    with authed_client() as client:
        response = client.post(f"/servers/{server_id}/assign-environment", json=payload)
    render_item(response.json(), output=output)


@app.command("beacon-state")
def beacon_state(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Show a server's Beacon reconciliation state (config_serial vs.
    applied_config_serial, last checkin/apply outcome). 404 if the server
    has never checked in (not beacon-managed)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/servers/{server_id}/beacon-state")
    render_item(response.json(), output=output)


beacon_token_app = typer.Typer(no_args_is_help=True, help="Manage Beacon agent tokens for a server.")
app.add_typer(beacon_token_app, name="beacon-token")


@beacon_token_app.command("issue")
def issue_beacon_token(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
    name: str = typer.Option(None, "--name", help="Optional label for this token."),
) -> None:
    """Mint a new Beacon token for a server. The raw token is shown
    exactly once here — save it, it can't be retrieved again."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/servers/{server_id}/beacon-token", json={"name": name})
    render_item(response.json(), output=output)


@beacon_token_app.command("list")
def list_beacon_tokens(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
) -> None:
    """List a server's Beacon tokens (metadata only, never the token/hash)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/servers/{server_id}/beacon-tokens")
    render_list(response.json(), output=output)


@beacon_token_app.command("revoke")
def revoke_beacon_token(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(...),
    token_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Revoke a Beacon token. The agent stops being able to authenticate
    on its next checkin attempt."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/servers/{server_id}/beacon-tokens/{token_id}/revoke")
    render_item(response.json(), output=output)
