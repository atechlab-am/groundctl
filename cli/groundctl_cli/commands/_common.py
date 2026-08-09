"""Shared helpers for command modules: build an authenticated client and
pull the --output option out of the Typer context."""

from __future__ import annotations

from contextlib import contextmanager

import typer

from groundctl_cli.client import GroundctlClient
from groundctl_cli.output import OutputFormat


def get_output(ctx: typer.Context) -> OutputFormat:
    parent = ctx.obj
    if parent is None and ctx.parent is not None:
        parent = ctx.parent.obj
    return (parent or {}).get("output", OutputFormat.table)


@contextmanager
def authed_client():
    client = GroundctlClient()
    try:
        client.ensure_authenticated()
        yield client
    finally:
        client.close()
