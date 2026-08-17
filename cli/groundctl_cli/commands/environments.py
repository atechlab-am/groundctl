"""groundctl environment create|update|list, plus a content-view
subcommand group for assign|list|promote|rollback|gpg-key|unassign.

Maps to /lifecycle-environments/* (domain term stays "environment" per
CLAUDE.md — "lifecycle environment" is the full domain term, "environment"
is the CLI-friendly short form used consistently as the subresource name).
An environment is pure promotion-path structure — any number of content
views can be assigned to it independently (EnvironmentContentView,
models.py) — hence the nested content-view subcommand group below.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import console, render_item, render_list

app = typer.Typer(no_args_is_help=True)
content_view_app = typer.Typer(no_args_is_help=True)
app.add_typer(content_view_app, name="content-view", help="Assign/promote/rollback content views within an environment.")


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    description: str = typer.Option(None, "--description"),
    prior_environment_id: uuid.UUID = typer.Option(
        None,
        "--prior-environment-id",
        help="Insert this environment right after another one in its promotion path. Omit to start a new path at "
        "position 0.",
    ),
) -> None:
    """Create a lifecycle environment. Matches Satellite's own "New
    Lifecycle Environment" dialog — just name/description/prior. An
    environment has NO content view of its own; assign one afterward with
    `groundctl environment content-view assign`."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "description": description,
        "prior_environment_id": str(prior_environment_id) if prior_environment_id else None,
    }
    with authed_client() as client:
        response = client.post("/lifecycle-environments", json=payload)
    render_item(response.json(), output=output)


@app.command()
def update(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    description: str = typer.Option(None, "--description"),
) -> None:
    """Set description. name/path_name/position stay fixed once created."""
    output = get_output(ctx)
    payload = {"description": description}
    with authed_client() as client:
        response = client.patch(f"/lifecycle-environments/{environment_id}", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_environments(
    ctx: typer.Context,
    path_name: str = typer.Option(None, "--path-name"),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List lifecycle environments (path structure only — see `environment
    content-view list` for what's actually assigned/published in one)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/lifecycle-environments",
            params={"path_name": path_name, "limit": limit, "offset": offset},
        )
    render_list(response.json(), output=output)


@content_view_app.command("assign")
def content_view_assign(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID to assign the content view to."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
    content_view_version_id: uuid.UUID = typer.Option(
        ..., "--content-view-version-id", help="Version to publish immediately — required on first assignment."
    ),
    gpg_key_id: str = typer.Option(
        None, "--gpg-key-id", help="Uppercase hex GPG key ID/fingerprint (16-40 chars)."
    ),
    allow_unsigned: bool = typer.Option(
        False, "--allow-unsigned", help="Required if --gpg-key-id is omitted."
    ),
) -> None:
    """Assign a content view to an environment and publish it there in one
    call — this is a pair's first-ever promote (see `promote` for every
    LATER one)."""
    output = get_output(ctx)
    payload = {
        "content_view_id": str(content_view_id),
        "content_view_version_id": str(content_view_version_id),
        "gpg_key_id": gpg_key_id,
        "allow_unsigned": allow_unsigned,
    }
    with authed_client() as client:
        response = client.post(f"/lifecycle-environments/{environment_id}/content-views", json=payload)
    render_item(response.json(), output=output)


@content_view_app.command("list")
def content_view_list(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
) -> None:
    """List content views assigned to an environment."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/lifecycle-environments/{environment_id}/content-views")
    render_list(response.json(), output=output)


@content_view_app.command("unassign")
def content_view_unassign(
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
) -> None:
    """Remove a content view assignment from an environment. Does not
    un-publish the aptly prefix itself."""
    with authed_client() as client:
        client.delete(f"/lifecycle-environments/{environment_id}/content-views/{content_view_id}")
    console.print("Unassigned.")


@content_view_app.command("promote")
def content_view_promote(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
    content_view_version_id: uuid.UUID = typer.Option(
        None,
        "--content-view-version-id",
        help="Version to promote to. Omit to publish-if-needed and promote the latest version.",
    ),
) -> None:
    """Promote a content view already assigned to this environment
    (see `assign` for a pair's first-ever promote). Never cuts a new
    snapshot from the mirror — see CLAUDE.md's immutable-snapshot
    invariant."""
    output = get_output(ctx)
    payload = {"content_view_version_id": str(content_view_version_id) if content_view_version_id else None}
    with authed_client() as client:
        response = client.post(
            f"/lifecycle-environments/{environment_id}/content-views/{content_view_id}/promote", json=payload
        )
    render_item(response.json(), output=output)


@content_view_app.command("rollback")
def content_view_rollback(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
    content_view_version_id: uuid.UUID = typer.Option(
        ..., "--content-view-version-id", help="A version this assignment has previously had live."
    ),
) -> None:
    """Roll back a content view assignment to a version it has previously
    had live in this environment."""
    output = get_output(ctx)
    payload = {"content_view_version_id": str(content_view_version_id)}
    with authed_client() as client:
        response = client.post(
            f"/lifecycle-environments/{environment_id}/content-views/{content_view_id}/rollback", json=payload
        )
    render_item(response.json(), output=output)


@content_view_app.command("gpg-key")
def content_view_gpg_key(
    environment_id: uuid.UUID = typer.Argument(..., help="Environment UUID."),
    content_view_id: uuid.UUID = typer.Option(..., "--content-view-id"),
    output_file: str = typer.Option(None, "--output-file", "-O", help="Write the armored key here instead of stdout."),
) -> None:
    """Fetch this assignment's ASCII-armored GPG signing public key."""
    with authed_client() as client:
        response = client.get(f"/lifecycle-environments/{environment_id}/content-views/{content_view_id}/gpg-key")
    if output_file:
        with open(output_file, "wb") as f:
            f.write(response.content)
        console.print(f"Wrote GPG key to {output_file}")
    else:
        console.print(response.text)
