"""Shared output rendering: --output table|json.

Commands call render_list/render_item with plain dicts (already
JSON-decoded from httpx responses) — no model classes required.
"""

from __future__ import annotations

import json as jsonlib
from enum import Enum

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


class OutputFormat(str, Enum):
    table = "table"
    json = "json"


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return jsonlib.dumps(value, default=str, separators=(",", ":"))
    return str(value)


def render_list(rows: list[dict], *, output: OutputFormat, columns: list[str] | None = None) -> None:
    if output == OutputFormat.json:
        console.print_json(jsonlib.dumps(rows, default=str))
        return

    if not rows:
        console.print("(no results)")
        return

    cols = columns or list(rows[0].keys())
    table = Table(show_lines=False)
    for col in cols:
        table.add_column(col)
    for row in rows:
        table.add_row(*[_stringify(row.get(c)) for c in cols])
    console.print(table)


def render_item(item: dict, *, output: OutputFormat) -> None:
    if output == OutputFormat.json:
        console.print_json(jsonlib.dumps(item, default=str))
        return

    table = Table(show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value")
    for key, value in item.items():
        table.add_row(key, _stringify(value))
    console.print(table)


def print_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def print_warning(message: str) -> None:
    err_console.print(f"[yellow]{message}[/yellow]")
