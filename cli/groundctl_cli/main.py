"""Root Typer app for the groundctl CLI. Registers all subcommand groups and
installs a top-level exception handler so expected API errors (401/403/404/
422/502, unreachable backend, "not logged in") print a single clean line to
stderr instead of a Python traceback.
"""

from __future__ import annotations

import sys

import typer

from groundctl_cli.errors import GroundctlError
from groundctl_cli.output import OutputFormat, err_console

app = typer.Typer(
    name="groundctl",
    help="Command-line client for Groundctl — content-lifecycle and patch-management control plane.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def main(
    ctx: typer.Context,
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format.", case_sensitive=False
    ),
) -> None:
    ctx.obj = {"output": output}


def _register_subcommands() -> None:
    from groundctl_cli.commands import (
        activation_keys,
        audit_logs,
        auth,
        compliance,
        content_views,
        environments,
        errata,
        host_groups,
        jobs,
        repositories,
        servers,
        sites,
    )

    app.add_typer(auth.app, name="auth", help="Login, logout, and session info.")
    app.add_typer(repositories.app, name="repository", help="Manage aptly-mirrored repositories.")
    app.add_typer(
        content_views.app,
        name="content-view",
        help=(
            "Manage content views and their versions. NOTE: the backend has no "
            "list/detail endpoint for content views — every command requires an "
            "explicit content-view ID (printed by `create`) rather than a name lookup."
        ),
    )
    app.add_typer(environments.app, name="environment", help="Manage lifecycle environments (dev/staging/prod).")
    app.add_typer(servers.app, name="server", help="Manage managed/content hosts.")
    app.add_typer(jobs.app, name="job", help="Trigger and inspect Ansible jobs.")
    app.add_typer(compliance.app, name="compliance", help="Package compliance checks and search.")
    app.add_typer(errata.app, name="errata", help="Security errata (USN/DSA advisories).")
    app.add_typer(host_groups.app, name="host-group", help="Manage host groups.")
    app.add_typer(activation_keys.app, name="activation-key", help="Manage self-registration activation keys.")
    app.add_typer(sites.app, name="site", help="Manage sites and relays.")
    app.add_typer(audit_logs.app, name="audit-log", help="Query and export the audit log (admin only).")


_register_subcommands()


def run() -> None:
    try:
        app()
    except GroundctlError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from None
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard against raw tracebacks
        err_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
