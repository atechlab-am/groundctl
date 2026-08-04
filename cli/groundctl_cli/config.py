"""Local CLI config: ~/.config/groundctl/config.toml.

Holds exactly two keys: api_url and refresh_token. The refresh token is the
only credential ever persisted to disk — never the access token (see
main.py / client.py). The config directory is created 0700 and the config
file is written 0600 so the refresh token isn't world/group readable.

Reading uses stdlib `tomllib` (read-only, Python 3.11+). Writing hand-rolls
a tiny TOML serializer instead of pulling in `tomli-w` — this is a 2-key
flat file, not worth an extra dependency, but string values must still be
properly quoted/escaped per the TOML spec (backslash and double-quote need
escaping; control characters are rejected outright by TOML's basic string
grammar and we don't expect them here, but escape what basic strings allow
and refuse the rest rather than emit invalid TOML).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("GROUNDCTL_CONFIG_DIR", "~/.config/groundctl")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"

_DIR_MODE = 0o700
_FILE_MODE = 0o600


def _toml_quote(value: str) -> str:
    """Render `value` as a TOML basic string (double-quoted), escaping the
    characters TOML's basic-string grammar requires escaped. Control
    characters other than tab are not valid in a TOML basic string at all;
    rather than silently mangle them we escape what's escapable and strip
    the rest, since api_url/refresh_token should never legitimately contain
    them.
    """
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            # Other control characters: drop rather than emit invalid TOML.
            continue
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


@dataclass
class Config:
    api_url: str | None = None
    refresh_token: str | None = None

    @property
    def is_logged_in(self) -> bool:
        return bool(self.api_url and self.refresh_token)


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        return Config()
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return Config(
        api_url=data.get("api_url"),
        refresh_token=data.get("refresh_token"),
    )


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, _DIR_MODE)

    lines = []
    if config.api_url is not None:
        lines.append(f"api_url = {_toml_quote(config.api_url)}")
    if config.refresh_token is not None:
        lines.append(f"refresh_token = {_toml_quote(config.refresh_token)}")
    content = "\n".join(lines) + "\n"

    # Write then chmod (not the reverse) — os.open with the mode set at
    # creation time avoids a window where the file briefly exists at the
    # default (often 0644) permissions before being tightened.
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    finally:
        pass
    os.chmod(CONFIG_FILE, _FILE_MODE)


def clear_config() -> None:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
