"""groundctl content-view create|publish|add-filter|versions

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
