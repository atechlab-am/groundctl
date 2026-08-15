#!/usr/bin/env python3
"""groundctl-beacon — optional pull-based agent for a groundctl-managed
content host (see ROADMAP.md Phase 9 and docs/beacon.md).

Deliberately a single file, stdlib-only (urllib, json, argparse, no third-
party dependencies) — every Debian/Ubuntu target already ships python3,
so "install" is just "copy this file," no build step, no venv, no pip.

Phase B scope (this file, today): authenticate with a BeaconToken, poll
POST /api/beacon/checkin, log what it received. It does NOT yet write any
files, run apt, or report back — that's Phase C (local reconciliation),
added on top of this same checkin call without changing its shape.

Config file: /etc/groundctl/beacon.conf, a simple KEY=VALUE file (mode
0600 — GROUNDCTL_BEACON_TOKEN is the one real secret involved), matching
the primary's own /etc/groundctl/groundctl.env convention.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AGENT_VERSION = "0.1.0"
DEFAULT_CONFIG_PATH = "/etc/groundctl/beacon.conf"

logger = logging.getLogger("groundctl-beacon")


class BeaconConfigError(Exception):
    """Raised for a missing/malformed config file — a real problem, not
    something to guess a default for, since GROUNDCTL_API_BASE_URL and
    GROUNDCTL_BEACON_TOKEN both come from the install script and have no
    sane fallback.
    """


def load_config(path: str) -> dict[str, str]:
    config_path = Path(path)
    if not config_path.is_file():
        raise BeaconConfigError(f"config file not found: {path}")

    values: dict[str, str] = {}
    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()

    for required in ("GROUNDCTL_API_BASE_URL", "GROUNDCTL_BEACON_TOKEN"):
        if required not in values or not values[required]:
            raise BeaconConfigError(f"{path} is missing required key: {required}")

    return values


class BeaconApiError(Exception):
    """Raised for both transport failures and non-2xx responses — same
    posture as this codebase's own AptlyError (app/aptly_client.py):
    callers don't need to distinguish "couldn't reach the server" from
    "server rejected the request," both mean this checkin attempt failed.
    """


def checkin(api_base_url: str, token: str, timeout: float = 15.0) -> dict:
    url = f"{api_base_url.rstrip('/')}/api/beacon/checkin"
    body = json.dumps({"agent_version": AGENT_VERSION}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BeaconApiError(f"checkin failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BeaconApiError(f"checkin failed: could not reach {api_base_url}: {exc.reason}") from exc


def run_once(config: dict[str, str]) -> dict:
    result = checkin(config["GROUNDCTL_API_BASE_URL"], config["GROUNDCTL_BEACON_TOKEN"])
    logger.info(
        "checkin OK — environment=%s config_serial=%s apt_source=%s",
        result["environment"]["name"],
        result["config_serial"],
        result["apt_source"]["filename"],
    )
    # Phase C adds: writing apt_source/keyring, removing
    # stale_source_filenames, running apt-get update, and reporting the
    # outcome via POST /api/beacon/report. Phase B intentionally stops
    # here — this checkin already proves the identity/protocol end to end
    # without touching anything on the host.
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="groundctl Beacon agent")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to beacon.conf")
    parser.add_argument("--once", action="store_true", help="check in once and exit (default: loop forever)")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="override the checkin interval in seconds (default: server-controlled, via checkin_interval_seconds)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        config = load_config(args.config)
    except BeaconConfigError as exc:
        logger.error("%s", exc)
        return 1

    interval = args.interval
    while True:
        try:
            result = run_once(config)
            interval = args.interval or result["checkin_interval_seconds"]
        except BeaconApiError as exc:
            logger.warning("%s", exc)
            interval = args.interval or 300

        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
