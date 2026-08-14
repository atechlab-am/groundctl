"""groundctl host-group create|list|show|set-members

Maps to /host-groups/*. "show" also surfaces /host-groups/{id}/members
since the group record itself doesn't embed membership.
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
    default_environment_id: uuid.UUID = typer.Option(None, "--default-environment-id"),
) -> None:
    """Create a host group."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "description": description,
        "default_environment_id": str(default_environment_id) if default_environment_id else None,
    }
    with authed_client() as client:
        response = client.post("/host-groups", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_host_groups(
    ctx: typer.Context,
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List host groups."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get("/host-groups", params={"limit": limit, "offset": offset})
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    host_group_id: uuid.UUID = typer.Argument(...),
    members: bool = typer.Option(False, "--members", help="Show member servers instead of the group record."),
    limit: int = typer.Option(100, "--limit", help="Only used with --members."),
    offset: int = typer.Option(0, "--offset", help="Only used with --members."),
) -> None:
    """Show a host group, or its member servers with --members."""
    output = get_output(ctx)
    with authed_client() as client:
        if members:
            response = client.get(f"/host-groups/{host_group_id}/members", params={"limit": limit, "offset": offset})
            render_list(response.json(), output=output)
            return
        response = client.get(f"/host-groups/{host_group_id}")
    render_item(response.json(), output=output)


@app.command("set-members")
def set_members(
    ctx: typer.Context,
    host_group_id: uuid.UUID = typer.Argument(...),
    server_id: list[uuid.UUID] = typer.Option(..., "--server-id", help="Repeatable. Replaces the full membership list."),
) -> None:
    """Replace a host group's full membership list."""
    output = get_output(ctx)
    payload = {"server_ids": [str(s) for s in server_id]}
    with authed_client() as client:
        response = client.put(f"/host-groups/{host_group_id}/members", json=payload)
    render_list(response.json(), output=output)
