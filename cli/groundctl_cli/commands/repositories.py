"""groundctl repository create|list|sync

Maps to POST/GET /repositories, POST /repositories/{name}/sync.
"""

from __future__ import annotations

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="aptly object name: letters, numbers, dots, underscores, hyphens only."),
    archive_url: str = typer.Option(..., "--archive-url", help="Upstream archive URL to mirror."),
    distribution: str = typer.Option(..., "--distribution", help="e.g. jammy, jammy-updates, jammy-security."),
    component: list[str] = typer.Option(..., "--component", help="Repeatable. e.g. --component main --component universe."),
    architecture: list[str] = typer.Option(..., "--architecture", help="Repeatable. e.g. --architecture amd64."),
) -> None:
    """Create (and mirror-create in aptly) a new repository."""
    output = get_output(ctx)
    payload = {
        "name": name,
        "archive_url": archive_url,
        "distribution": distribution,
        "components": component,
        "architectures": architecture,
    }
    with authed_client() as client:
        response = client.post("/repositories", json=payload)
    render_item(response.json(), output=output)


@app.command("list")
def list_repositories(
    ctx: typer.Context,
    distribution: str = typer.Option(None, "--distribution", help="Filter by distribution."),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List repositories."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/repositories", params={"distribution": distribution, "limit": limit, "offset": offset}
        )
    render_list(response.json(), output=output)


@app.command()
def sync(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Repository name to sync from upstream."),
) -> None:
    """Trigger an async sync of a repository's mirror from its upstream
    archive. Returns the tracked Job immediately (status starts "pending") —
    use `groundctl job show <id>` to follow progress, sync no longer blocks
    until completion.
    """
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/repositories/{name}/sync")
    render_item(response.json(), output=output)
