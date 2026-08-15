#!/usr/bin/env python3
"""groundctl-beacon — optional pull-based agent for a groundctl-managed
content host (see ROADMAP.md Phase 9 and docs/beacon.md).

Deliberately a single file, stdlib-only (urllib, json, argparse, no third-
party dependencies) — every Debian/Ubuntu target already ships python3,
so "install" is just "copy this file," no build step, no venv, no pip.

Scope (this file, today): authenticate, checkin, reconcile the local apt
source/keyring (write the current one, remove every other
groundctl-managed file), run `apt-get update` with a small bounded retry,
report the outcome via POST /api/beacon/report. Also pushes full facts
(installed packages, os/kernel) via POST /api/beacon/facts when the
checkin response requests it, and executes any dispatched actions
(currently just apply_updates) returned in the checkin's actions list,
reporting each outcome back via /report with that action's id.

Config file: /etc/groundctl/beacon.conf, a simple KEY=VALUE file (mode
0600 — GROUNDCTL_BEACON_TOKEN is the one real secret involved), matching
the primary's own /etc/groundctl/groundctl.env convention.

File-write surface is a hardcoded allowlist — exactly two directories,
exactly the "groundctl-*" prefix — enforced here in the agent's own code,
not merely by what the server happens to send (see docs/beacon.md's
non-goals list). This agent never writes/removes anything outside those
two directories and that one filename prefix.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AGENT_VERSION = "0.3.0"
DEFAULT_CONFIG_PATH = "/etc/groundctl/beacon.conf"

# The ONLY two directories this agent will ever write to or remove files
# from, and the ONLY filename prefix it will ever touch within them — a
# hardcoded allowlist, not derived from anything the server sends.
SOURCES_LIST_DIR = Path("/etc/apt/sources.list.d")
KEYRINGS_DIR = Path("/etc/apt/keyrings")
MANAGED_PREFIX = "groundctl-"

APT_UPDATE_MAX_ATTEMPTS = 3
APT_UPDATE_RETRY_DELAY_SECONDS = 5
APT_UPDATE_TIMEOUT_SECONDS = 120

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
    "server rejected the request," both mean this attempt failed.
    """


def _api_post(api_base_url: str, token: str, path: str, body: dict, timeout: float = 15.0) -> dict:
    url = f"{api_base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
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
        raise BeaconApiError(f"{path} failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BeaconApiError(f"{path} failed: could not reach {api_base_url}: {exc.reason}") from exc


def checkin(api_base_url: str, token: str) -> dict:
    return _api_post(api_base_url, token, "/api/beacon/checkin", {"agent_version": AGENT_VERSION})


def report(
    api_base_url: str,
    token: str,
    config_serial: int,
    outcome: str,
    detail: str | None,
    action_id: str | None = None,
) -> dict:
    body = {"config_serial": config_serial, "outcome": outcome, "detail": detail}
    if action_id is not None:
        body["action_id"] = action_id
    return _api_post(api_base_url, token, "/api/beacon/report", body)


def push_facts(api_base_url: str, token: str) -> dict:
    """Gathers the same shape of facts gather_facts_task collects over SSH
    (installed packages via dpkg-query, no version comparison performed
    here — that's do_check_compliance's job server-side, per CLAUDE.md's
    rule against ever comparing Debian versions client-side or with
    string equality).
    """
    installed_packages: list[dict] = []
    proc = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${Architecture}\\n"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode == 0:
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                installed_packages.append({"name": parts[0], "version": parts[1], "arch": parts[2]})

    os_distribution = None
    os_version = None
    os_release_path = Path("/etc/os-release")
    if os_release_path.is_file():
        os_release = {}
        for line in os_release_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                os_release[key.strip()] = value.strip().strip('"')
        os_distribution = os_release.get("ID")
        os_version = os_release.get("VERSION_ID")

    kernel = None
    uname_proc = subprocess.run(["uname", "-r"], capture_output=True, timeout=10, check=False)
    if uname_proc.returncode == 0:
        kernel = uname_proc.stdout.decode("utf-8", errors="replace").strip()

    uptime_seconds = None
    uptime_path = Path("/proc/uptime")
    if uptime_path.is_file():
        uptime_seconds = int(float(uptime_path.read_text(encoding="utf-8").split()[0]))

    return _api_post(
        api_base_url,
        token,
        "/api/beacon/facts",
        {
            "os_distribution": os_distribution,
            "os_version": os_version,
            "kernel": kernel,
            "uptime_seconds": uptime_seconds,
            "disk": [],
            "services": [],
            "installed_packages": installed_packages,
        },
        timeout=60.0,
    )


def execute_action(action: dict) -> tuple[bool, str]:
    """Runs a dispatched action locally and returns (success, detail) for
    /report. Enum-scoped by action["type"] (never a free-form command
    string from the server — see docs/beacon.md's non-goals list: no
    arbitrary command execution channel here, ever).
    """
    action_type = action.get("type")
    if action_type == "apply_updates":
        update_ok, update_output = apt_get_update()
        if not update_ok:
            return False, update_output[:16000]
        proc = subprocess.run(
            ["apt-get", "upgrade", "-y"],
            capture_output=True,
            timeout=APT_UPDATE_TIMEOUT_SECONDS,
            check=False,
        )
        output = update_output + proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
            "utf-8", errors="replace"
        )
        return proc.returncode == 0, output[:16000]
    return False, f"unknown action type: {action_type}"


def _write_file(path: Path, content: str, mode: int) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def reconcile_apt_sources(checkin_result: dict) -> None:
    """Writes the current apt_source (+ keyring, if signed) and removes
    every OTHER groundctl-managed file in the two allowlisted directories
    — mirrors bootstrap_client.yml's replace-in-place logic exactly
    (glob for "groundctl-*", keep only what belongs to the current
    environment), just executed locally instead of over SSH by Ansible.
    Raises on any real filesystem error (permission denied, disk full,
    etc.) — the caller treats that as a failed reconciliation attempt.
    """
    apt_source = checkin_result["apt_source"]
    keep_filenames = {apt_source["filename"]}
    if apt_source["keyring_filename"]:
        keep_filenames.add(apt_source["keyring_filename"])

    for directory in (SOURCES_LIST_DIR, KEYRINGS_DIR):
        if not directory.is_dir():
            continue
        for existing in directory.glob(f"{MANAGED_PREFIX}*"):
            if existing.name not in keep_filenames:
                logger.info("removing stale groundctl-managed file: %s", existing)
                existing.unlink(missing_ok=True)

    sources_path = SOURCES_LIST_DIR / apt_source["filename"]
    logger.info("writing %s", sources_path)
    _write_file(sources_path, apt_source["contents"], 0o644)

    gpg_public_key = checkin_result.get("gpg_public_key")
    if apt_source["keyring_filename"] and gpg_public_key:
        keyring_path = KEYRINGS_DIR / apt_source["keyring_filename"]
        logger.info("installing signing key: %s", keyring_path)
        # Dearmor via gpg itself (same tool bootstrap_client.yml shells
        # out to) rather than reimplementing OpenPGP framing — armored
        # key in via stdin, binary keyring out via stdout, no temp files.
        proc = subprocess.run(
            ["gpg", "--dearmor"],
            input=gpg_public_key.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"gpg --dearmor failed: {proc.stderr.decode('utf-8', errors='replace')}")
        keyring_path.write_bytes(proc.stdout)
        keyring_path.chmod(0o644)


def apt_get_update() -> tuple[bool, str]:
    """Runs `apt-get update`, retrying a few times with a short delay
    before giving up — transient network blips shouldn't need to wait a
    full checkin interval to self-heal. Bounded and stateless (no
    persistence across checkins, no backoff growth) — matches the
    agent's own "thin, no local decision-making beyond this one retry
    loop" design.
    """
    last_output = ""
    for attempt in range(1, APT_UPDATE_MAX_ATTEMPTS + 1):
        proc = subprocess.run(
            ["apt-get", "update"],
            capture_output=True,
            timeout=APT_UPDATE_TIMEOUT_SECONDS,
            check=False,
        )
        last_output = (proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace"))
        if proc.returncode == 0:
            return True, last_output
        logger.warning("apt-get update failed (attempt %d/%d): %s", attempt, APT_UPDATE_MAX_ATTEMPTS, last_output.strip())
        if attempt < APT_UPDATE_MAX_ATTEMPTS:
            time.sleep(APT_UPDATE_RETRY_DELAY_SECONDS)
    return False, last_output


def run_once(config: dict[str, str]) -> dict:
    api_base_url = config["GROUNDCTL_API_BASE_URL"]
    token = config["GROUNDCTL_BEACON_TOKEN"]

    result = checkin(api_base_url, token)
    logger.info(
        "checkin OK — environment=%s config_serial=%s apt_source=%s",
        result["environment"]["name"],
        result["config_serial"],
        result["apt_source"]["filename"],
    )

    try:
        reconcile_apt_sources(result)
    except OSError as exc:
        logger.error("failed to write apt source/keyring: %s", exc)
        report(api_base_url, token, result["config_serial"], "failed", str(exc)[:16000])
        return result
    except RuntimeError as exc:
        logger.error("%s", exc)
        report(api_base_url, token, result["config_serial"], "failed", str(exc)[:16000])
        return result

    ok, apt_output = apt_get_update()
    if ok:
        logger.info("apt-get update succeeded")
        report(api_base_url, token, result["config_serial"], "success", apt_output[:16000])
    else:
        logger.error("apt-get update failed after %d attempts", APT_UPDATE_MAX_ATTEMPTS)
        report(api_base_url, token, result["config_serial"], "failed", apt_output[:16000])

    if result.get("facts_requested"):
        try:
            push_facts(api_base_url, token)
            logger.info("facts pushed")
        except BeaconApiError as exc:
            # Non-fatal — facts are best-effort telemetry, not part of the
            # reconciliation contract; a failed push just means the next
            # due checkin tries again.
            logger.warning("facts push failed: %s", exc)

    for action in result.get("actions", []):
        logger.info("executing dispatched action: id=%s type=%s", action["id"], action["type"])
        action_ok, action_detail = execute_action(action)
        report(
            api_base_url,
            token,
            result["config_serial"],
            "success" if action_ok else "failed",
            action_detail,
            action_id=action["id"],
        )

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
