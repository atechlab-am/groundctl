"""groundctl activation-key create|list|show|revoke

Maps to /activation-keys/*. The raw token is only ever present in the
POST /activation-keys response body (ActivationKeyCreateResponse) — every
other read (list/show) uses ActivationKeyRead, which omits it entirely, so
there is no way to retrieve it again after creation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import OutputFormat, console, err_console, render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    environment_id: uuid.UUID = typer.Option(..., "--environment-id"),
    host_group_id: uuid.UUID = typer.Option(None, "--host-group-id"),
    tag: list[str] = typer.Option(None, "--tag", help="Repeatable."),
    expires_at: datetime = typer.Option(None, "--expires-at", help="ISO 8601 datetime. Defaults to a server-side TTL if omitted."),
    max_uses: int = typer.Option(None, "--max-uses"),
) -> None:
    """Create an activation key. The raw token is printed ONCE, here — it is
    never retrievable again (the server only stores a hash of it)."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "environment_id": str(environment_id),
        "host_group_id": str(host_group_id) if host_group_id else None,
        "tags": tag or [],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "max_uses": max_uses,
    }
    with authed_client() as client:
        response = client.post("/activation-keys", json=payload)
    body = response.json()

    if output == OutputFormat.json:
        render_item(body, output=output)
    else:
        render_item(body, output=output)
        err_console.print(
            "\n[bold yellow]This token will not be shown again — store it now.[/bold yellow]"
        )
    console.print(f"\n[bold]token:[/bold] {body['token']}")


@app.command("list")
def list_activation_keys(
    ctx: typer.Context,
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List activation keys (never includes the raw token)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get("/activation-keys", params={"limit": limit, "offset": offset})
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    activation_key_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Show an activation key (never includes the raw token)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/activation-keys/{activation_key_id}")
    render_item(response.json(), output=output)


@app.command()
def revoke(
    ctx: typer.Context,
    activation_key_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Revoke an activation key."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/activation-keys/{activation_key_id}/revoke")
    render_item(response.json(), output=output)
