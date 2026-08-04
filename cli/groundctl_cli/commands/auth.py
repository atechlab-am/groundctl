"""groundctl auth login|logout|whoami

login/refresh/logout use the plain JSON-body flow (POST /auth/login,
/auth/refresh, /auth/logout) — distinct from the cookie-based /auth/ui-*
endpoints built for the web UI. Only the refresh token is ever persisted to
disk; the password is always prompted interactively (never a CLI argument,
to avoid a shell-history leak) and the access token lives only in memory
for the current invocation.
"""

from __future__ import annotations

import typer

from groundctl_cli.client import GroundctlClient
from groundctl_cli.commands._common import authed_client, get_output
from groundctl_cli.config import Config, load_config, save_config
from groundctl_cli.output import print_success, render_item

app = typer.Typer(no_args_is_help=True)


@app.command()
def login(
    api_url: str = typer.Option(None, "--api-url", help="Base URL of the Groundctl API, e.g. https://groundctl.example.com"),
    username: str = typer.Option(None, "--username", help="Username. Prompted if not given."),
) -> None:
    """Log in and store a refresh token in ~/.config/groundctl/config.toml.

    The access token is never persisted. The password is always prompted —
    passing it as a CLI argument would leak it into shell history.
    """
    config = load_config()
    resolved_api_url = api_url or config.api_url
    if not resolved_api_url:
        resolved_api_url = typer.prompt("API URL")

    resolved_username = username or typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)

    config = Config(api_url=resolved_api_url, refresh_token=None)
    save_config(config)

    client = GroundctlClient(config)
    try:
        client.login(resolved_username, password)
    finally:
        client.close()

    print_success(f"Logged in as {resolved_username} ({resolved_api_url})")


@app.command()
def logout() -> None:
    """Revoke the stored refresh token server-side and clear local config."""
    config = load_config()
    if not config.refresh_token:
        print_success("Already logged out.")
        return

    client = GroundctlClient(config)
    try:
        client.logout()
    finally:
        client.close()
    print_success("Logged out.")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Show the currently authenticated user."""
    output = get_output(ctx)
    with authed_client() as client:
        response = client.get("/auth/me")
    render_item(response.json(), output=output)
