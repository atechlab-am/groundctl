"""groundctl content-view create|publish|publish-and-promote|add-filter|
versions|set-version-description

LIMITATION (matches a known backend gap, also hit by the web UI): there is
no GET list/detail endpoint for content views on the backend
(app/routers/content_views.py only exposes POST /content-views,
POST /{id}/filters, POST /{id}/publish, GET /{id}/versions). This CLI does
NOT invent a new backend endpoint to work around that — every subcommand
here requires an explicit content-view ID (the UUID printed by `create`),
the same workaround the web UI uses. There is no `content-view list` or
`content-view show` command.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Manage content views. NOTE: the backend has no list/detail endpoint for "
        "content views (see app/routers/content_views.py) — every command here "
        "requires an explicit content-view ID rather than a name lookup. Save the "
        "ID printed by `content-view create`."
    ),
)


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    repository_id: list[uuid.UUID] = typer.Option(
        ..., "--repository-id", help="Repeatable. At least one repository UUID."
    ),
) -> None:
    """Create a content view from one or more repositories."""
    output = get_output(ctx)
    payload = {"name": name, "repository_ids": [str(r) for r in repository_id]}
    with authed_client() as client:
        response = client.post("/content-views", json=payload)
    render_item(response.json(), output=output)


@app.command()
def publish(
    ctx: typer.Context,
    content_view_id: uuid.UUID = typer.Argument(..., help="Content view UUID."),
) -> None:
    """Cut a new content view version if the member repositories changed
    since the last publish, else return the existing latest version
    unchanged (version_cut in the response tells you which happened)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/content-views/{content_view_id}/publish")
    render_item(response.json(), output=output)


@app.command("publish-and-promote")
def publish_and_promote(
    ctx: typer.Context,
    content_view_id: uuid.UUID = typer.Argument(..., help="Content view UUID."),
    environment_id: uuid.UUID = typer.Option(..., "--environment-id", help="Environment to promote the new version to."),
    description: str = typer.Option(None, "--description", help="Optional, applied to the version once cut."),
    force: bool = typer.Option(True, "--force/--no-force", help="Always cut a new version, even if unchanged since the last one."),
) -> None:
    """Cut a new version and promote it to an environment as ONE tracked
    Job — unlike `publish` (synchronous), this returns immediately; poll
    with `groundctl job show <id>`. Prefer this over `publish` +
    `groundctl environment promote` when you also want to promote, since
    aptly's publish/switch-publish call can run long."""
    output = get_output(ctx)
    payload = {"environment_id": str(environment_id), "force": force, "description": description}
    with authed_client() as client:
        response = client.post(f"/content-views/{content_view_id}/publish-and-promote", json=payload)
    render_item(response.json(), output=output)


@app.command("add-filter")
def add_filter(
    ctx: typer.Context,
    content_view_id: uuid.UUID = typer.Argument(..., help="Content view UUID."),
    filter_type: str = typer.Option(..., "--filter-type", help="include | exclude | errata_since"),
    pattern: str = typer.Option(
        ...,
        "--pattern",
        help="Package name/wildcard pattern (include/exclude), or an ISO date e.g. 2026-01-01 (errata_since).",
    ),
) -> None:
    """Add a package filter to a content view (applied on next publish)."""
    output = get_output(ctx)
    payload = {"filter_type": filter_type, "pattern": pattern}
    with authed_client() as client:
        response = client.post(f"/content-views/{content_view_id}/filters", json=payload)
    render_item(response.json(), output=output)


@app.command()
def versions(
    ctx: typer.Context,
    content_view_id: uuid.UUID = typer.Argument(..., help="Content view UUID."),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List versions of a content view, newest first."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            f"/content-views/{content_view_id}/versions", params={"limit": limit, "offset": offset}
        )
    render_list(response.json(), output=output)


@app.command("set-version-description")
def set_version_description(
    ctx: typer.Context,
    content_view_id: uuid.UUID = typer.Argument(..., help="Content view UUID."),
    version_id: uuid.UUID = typer.Argument(..., help="Content view version UUID (see `versions`)."),
    description: str = typer.Option(
        None, "--description", help="Omit to clear the description. The version NUMBER is unaffected — annotation only."
    ),
) -> None:
    """Set or clear a version's description. Doesn't rename or renumber
    the version — matches Satellite, where versions are numbered, never
    renamed, only annotated."""
    output = get_output(ctx)
    payload = {"description": description}
    with authed_client() as client:
        response = client.patch(f"/content-views/{content_view_id}/versions/{version_id}", json=payload)
    render_item(response.json(), output=output)
