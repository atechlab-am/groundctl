"""groundctl environment create|update|list|promote|rollback|gpg-key

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
    content_view_id: uuid.UUID = typer.Option(
        None,
        "--content-view-id",
        help="Content view this environment belongs to. Required unless --prior-environment-id is given, in which "
        "case it's inherited from that environment instead.",
    ),
    description: str = typer.Option(None, "--description"),
    prior_environment_id: uuid.UUID = typer.Option(
        None,
        "--prior-environment-id",
        help="Insert this environment right after another one in its promotion path (inherits its content view). "
        "Omit to start a new path at position 0 on --content-view-id.",
    ),
    gpg_key_id: str = typer.Option(
        None, "--gpg-key-id", help="Uppercase hex GPG key ID/fingerprint (16-40 chars). Can also be set later via `update`."
    ),
) -> None:
    """Create a lifecycle environment. Matches Satellite's own "New
    Lifecycle Environment" dialog — name/description/prior, plus which
    content view it belongs to. Every content view already has its own
    auto-created "Library" root (see `groundctl content-view create`) —
    this command is for every OTHER environment in that content view's
    promotion path. release/publish_prefix are NOT set here; they're
    derived automatically the first time you `promote` something to it."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "content_view_id": str(content_view_id) if content_view_id else None,
        "description": description,
        "prior_environment_id": str(prior_environment_id) if prior_environment_id else None,
        "gpg_key_id": gpg_key_id,
    }
    with authed_client() as client:
        response = client.post("/lifecycle-environments", json=payload)
    render_item(response.json(), output=output)


@app.command()
def update(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    description: str = typer.Option(None, "--description"),
    gpg_key_id: str = typer.Option(None, "--gpg-key-id"),
) -> None:
    """Set description and/or gpg_key_id. This is how you add a signing
    key to an environment before its first promote (otherwise `promote`
    requires --allow-unsigned). Everything else (content_view_id/release/
    publish_prefix) is locked in by `promote` and can't be changed here."""
    output = get_output(ctx)
    payload = {"description": description, "gpg_key_id": gpg_key_id}
    with authed_client() as client:
        response = client.patch(f"/lifecycle-environments/{environment_id}", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_environments(
    ctx: typer.Context,
    path_name: str = typer.Option(None, "--path-name"),
    content_view_id: uuid.UUID = typer.Option(
        None, "--content-view-id", help="Exact match — every environment on this content view, Library included."
    ),
    promotable_for_content_view_id: uuid.UUID = typer.Option(
        None,
        "--promotable-for-content-view-id",
        help="Environments tied to this content view, OR (legacy rows only) never promoted anywhere yet.",
    ),
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
                "promotable_for_content_view_id": (
                    str(promotable_for_content_view_id) if promotable_for_content_view_id else None
                ),
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
        help="Version to promote to. REQUIRED on this environment's first-ever promote (that's when release/"
        "publish_prefix get derived and locked in). Omit on later promotes to publish-if-needed and promote the "
        "latest version.",
    ),
    allow_unsigned: bool = typer.Option(
        False,
        "--allow-unsigned",
        help="Only consulted on a first promote when the environment has no gpg_key_id set (see `update`).",
    ),
) -> None:
    """Re-point an environment's publish prefix at an existing content view
    version (never cuts a new snapshot from the mirror — see CLAUDE.md's
    immutable-snapshot invariant)."""
    output = get_output(ctx)
    payload = {
        "content_view_version_id": str(content_view_version_id) if content_view_version_id else None,
        "allow_unsigned": allow_unsigned,
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
