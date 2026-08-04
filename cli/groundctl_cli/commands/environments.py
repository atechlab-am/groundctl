"""groundctl environment create|list|promote|rollback|gpg-key

Maps to /lifecycle-environments/* (domain term stays "environment" per
CLAUDE.md — "lifecycle environment" is the full domain term, "environment"
is the CLI-friendly short form used consistently as the subresource name).
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import console, render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    path_name: str = typer.Option(..., "--path-name", help="Promotion path this environment belongs to, e.g. 'default'."),
    position: int = typer.Option(..., "--position", help="Position within the path (0 = first, no predecessor)."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
    distro: str = typer.Option(..., "--distro"),
    release: str = typer.Option(..., "--release", help="apt sources.list distribution field."),
    publish_prefix: str = typer.Option(..., "--publish-prefix", help="aptly publish prefix / stable URL path."),
    gpg_key_id: str = typer.Option(
        None, "--gpg-key-id", help="Uppercase hex GPG key ID/fingerprint (16-40 chars). Required unless --allow-unsigned."
    ),
    allow_unsigned: bool = typer.Option(
        False,
        "--allow-unsigned",
        help="Explicit opt-out of GPG signing (logged, see docs/gpg-signing.md). Off by default.",
    ),
) -> None:
    """Create a lifecycle environment."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "path_name": path_name,
        "position": position,
        "content_view_id": str(content_view_id),
        "distro": distro,
        "release": release,
        "publish_prefix": publish_prefix,
        "gpg_key_id": gpg_key_id,
        "allow_unsigned": allow_unsigned,
    }
    with authed_client() as client:
        response = client.post("/lifecycle-environments", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_environments(
    ctx: typer.Context,
    path_name: str = typer.Option(None, "--path-name"),
    content_view_id: uuid.UUID = typer.Option(None, "--content-view-id"),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List lifecycle environments."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/lifecycle-environments",
            params={
                "path_name": path_name,
                "content_view_id": str(content_view_id) if content_view_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
    render_list(response.json(), output=output)


@app.command()
def promote(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID to promote."),
    content_view_version_id: uuid.UUID = typer.Option(
        None,
        "--content-view-version-id",
        help="Version to promote to. Omit to publish-if-needed and promote the content view's latest version.",
    ),
) -> None:
    """Re-point an environment's publish prefix at an existing content view
    version (never cuts a new snapshot from the mirror — see CLAUDE.md's
    immutable-snapshot invariant)."""
    output = get_output(ctx)
    payload = {
        "content_view_version_id": str(content_view_version_id) if content_view_version_id else None
    }
    with authed_client() as client:
        response = client.post(f"/lifecycle-environments/{environment_id}/promote", json=payload)
    render_item(response.json(), output=output)


@app.command()
def rollback(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID to roll back."),
    content_view_version_id: uuid.UUID = typer.Option(
        ..., "--content-view-version-id", help="A version this environment has previously had live."
    ),
) -> None:
    """Roll back an environment to a version it has previously had live."""
    output = get_output(ctx)
    payload = {"content_view_version_id": str(content_view_version_id)}
    with authed_client() as client:
        response = client.post(f"/lifecycle-environments/{environment_id}/rollback", json=payload)
    render_item(response.json(), output=output)


@app.command("gpg-key")
def gpg_key(
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    output_file: str = typer.Option(None, "--output-file", "-O", help="Write the armored key here instead of stdout."),
) -> None:
    """Fetch the environment's ASCII-armored GPG signing public key."""
    with authed_client() as client:
        response = client.get(f"/lifecycle-environments/{environment_id}/gpg-key")
    if output_file:
        with open(output_file, "wb") as f:
            f.write(response.content)
        console.print(f"Wrote GPG key to {output_file}")
    else:
        console.print(response.text)
