"""groundctl job list|show|trigger-bootstrap|apply-updates|gather-facts|
bulk-apply-updates|run-command|manage-package|cancel

Maps to /jobs/*. apply-updates and gather-facts take environment_id as a
query param on the backend (not a body field) — preserved here as a Typer
option rather than folded into a JSON body.
"""

from __future__ import annotations

import uuid

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import render_item, render_list

app = typer.Typer(no_args_is_help=True)


def _target_selector(host_group_id: uuid.UUID | None, server_id: list[uuid.UUID]) -> dict:
    return {
        "host_group_id": str(host_group_id) if host_group_id else None,
        "server_ids": [str(s) for s in server_id] if server_id else None,
    }


@app.command("list")
def list_jobs(
    ctx: typer.Context,
    job_type: str = typer.Option(
        None, "--job-type", help="bootstrap|apply_updates|gather_facts|bulk_apply_updates|run_command|manage_package"
    ),
    status: str = typer.Option(None, "--status", help="pending|running|success|failed"),
    environment_id: uuid.UUID = typer.Option(None, "--environment-id"),
    server_id: uuid.UUID = typer.Option(None, "--server-id"),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List jobs, newest first."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/jobs",
            params={
                "job_type": job_type,
                "status": status,
                "environment_id": str(environment_id) if environment_id else None,
                "server_id": str(server_id) if server_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
    render_list(response.json(), output=output)


@app.command()
def show(
    ctx: typer.Context,
    job_id: uuid.UUID = typer.Argument(..., help="Job UUID. Includes log_output."),
) -> None:
    """Show a job's status and log output."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(f"/jobs/{job_id}")
    render_item(response.json(), output=output)


@app.command("trigger-bootstrap")
def trigger_bootstrap(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Argument(..., help="Server to bootstrap."),
) -> None:
    """Trigger the bootstrap job for a single server (overwrites
    /etc/apt/sources.list on that host — see CLAUDE.md's destructive-
    operations section)."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/jobs/bootstrap/{server_id}")
    render_item(response.json(), output=output)


@app.command("apply-updates")
def apply_updates(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Option(..., "--environment-id", help="Apply to every server in this environment."),
) -> None:
    """Trigger apply-updates across every server in an environment."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post("/jobs/apply-updates", params={"environment_id": str(environment_id)})
    render_item(response.json(), output=output)


@app.command("gather-facts")
def gather_facts(
    ctx: typer.Context,
    environment_id: uuid.UUID = typer.Option(..., "--environment-id", help="Gather facts from every server in this environment."),
) -> None:
    """Trigger fact-gathering across every server in an environment."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post("/jobs/gather-facts", params={"environment_id": str(environment_id)})
    render_item(response.json(), output=output)


@app.command("bulk-apply-updates")
def bulk_apply_updates(
    ctx: typer.Context,
    host_group_id: uuid.UUID = typer.Option(None, "--host-group-id", help="Exactly one of --host-group-id / --server-id required."),
    server_id: list[uuid.UUID] = typer.Option(None, "--server-id", help="Repeatable."),
) -> None:
    """Trigger apply-updates against an ad-hoc set of servers or a host group."""
    output = get_output(ctx)
    payload = _target_selector(host_group_id, server_id)
    with authed_client() as client:
        response = client.post("/jobs/bulk-apply-updates", json=payload)
    render_item(response.json(), output=output)


@app.command("run-command")
def run_command(
    ctx: typer.Context,
    command: str = typer.Option(..., "--command", help="Run literally, no shell — no ; | & $ ` <> or newlines."),
    host_group_id: uuid.UUID = typer.Option(None, "--host-group-id", help="Exactly one of --host-group-id / --server-id required."),
    server_id: list[uuid.UUID] = typer.Option(None, "--server-id", help="Repeatable."),
) -> None:
    """Run an arbitrary command across a set of servers. Admin only."""
    output = get_output(ctx)
    payload = _target_selector(host_group_id, server_id)
    payload["command"] = command
    with authed_client() as client:
        response = client.post("/jobs/run-command", json=payload)
    render_item(response.json(), output=output)


@app.command("manage-package")
def manage_package(
    ctx: typer.Context,
    server_id: uuid.UUID = typer.Option(..., "--server-id"),
    package_name: str = typer.Option(..., "--package-name"),
    action: str = typer.Option(..., "--action", help="install | remove"),
) -> None:
    """Install or remove a package on a single server."""
    output = get_output(ctx)
    payload = {"server_id": str(server_id), "package_name": package_name, "action": action}
    with authed_client() as client:
        response = client.post("/jobs/manage-package", json=payload)
    render_item(response.json(), output=output)


@app.command()
def cancel(
    ctx: typer.Context,
    job_id: uuid.UUID = typer.Argument(...),
) -> None:
    """Cancel a pending or running job."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.post(f"/jobs/{job_id}/cancel")
    render_item(response.json(), output=output)
