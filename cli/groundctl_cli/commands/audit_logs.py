"""groundctl audit-log list|export

Maps to /audit-logs/*. Both endpoints are admin-only on the backend — a
non-admin user gets a plain 403 from require_role(Role.admin), which
errors.py renders as a clean one-line message, not a stack trace.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import typer

from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.output import console, render_list

app = typer.Typer(no_args_is_help=True, help="Query and export the audit log. Admin only.")


@app.command("list")
def list_audit_logs(
    ctx: typer.Context,
    user_id: uuid.UUID = typer.Option(None, "--user-id"),
    action: str = typer.Option(None, "--action", help="e.g. login, create_repository, switch_publish."),
    resource_type: str = typer.Option(None, "--resource-type"),
    since: datetime = typer.Option(None, "--since", help="ISO 8601 datetime."),
    until: datetime = typer.Option(None, "--until", help="ISO 8601 datetime."),
    limit: int = typer.Option(100, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """List audit log entries."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get(
            "/audit-logs",
            params={
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "resource_type": resource_type,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
                "limit": limit,
                "offset": offset,
            },
        )
    render_list(response.json(), output=output)


@app.command()
def export(
    user_id: uuid.UUID = typer.Option(None, "--user-id"),
    action: str = typer.Option(None, "--action"),
    resource_type: str = typer.Option(None, "--resource-type"),
    since: datetime = typer.Option(None, "--since", help="ISO 8601 datetime."),
    until: datetime = typer.Option(None, "--until", help="ISO 8601 datetime."),
    output_file: str = typer.Option(None, "--output-file", "-O", help="Write CSV here instead of stdout."),
) -> None:
    """Export audit log entries as CSV."""
    with authed_client() as client:
        response = client.get(
            "/audit-logs/export",
            params={
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "resource_type": resource_type,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
            },
        )
    if output_file:
        with open(output_file, "w", newline="") as f:
            f.write(response.text)
        console.print(f"Wrote CSV to {output_file}")
    else:
        console.print(response.text, end="")
