"""Single canonical renderer for a groundctl-managed apt sources.list
entry — used by both bootstrap_client.yml's SSH path (via bootstrap_task's
extra_vars) and the Beacon checkin response (app/routers/beacon.py).

Collapses what used to be an implicit two-renderer situation (the Jinja
template in bootstrap_client.yml, and — once Beacon exists — a second,
inevitably-divergent renderer needed to hand the beacon something to
write) into one place. This directly addresses CLAUDE.md's documented
apt sources.list injection concern: a crafted publish_prefix/release could
inject an extra `deb` line pointing at an attacker-controlled archive.
Validating the inputs once, here, and having every consumer treat the
*output* as an opaque string it never reconstructs, is the point — the
beacon in particular ships this string verbatim rather than being handed
publish_prefix/release/components to concatenate itself.
"""

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AptSource:
    # e.g. "groundctl-dev.list" — matches bootstrap_client.yml's existing
    # groundctl-<environment_name>.list naming exactly.
    filename: str
    # The full, ready-to-write file contents — a single `deb [...] url
    # release components` line, newline-terminated.
    contents: str
    # Keyring filename, only set when signed (gpg_key_id is not None).
    # None means [trusted=yes] — no keyring file involved.
    keyring_filename: str | None


def render_apt_source(
    environment_name: str,
    content_view_name: str,
    published_repo_base_url: str,
    publish_prefix: str,
    release: str,
    components: list[str],
    gpg_key_id: str | None,
) -> AptSource:
    """Pure function, no DB/network access — callers resolve
    environment/content-view/components/base_url first (see tasks.py's
    bootstrap_task and app/routers/beacon.py's checkin handler for the two
    call sites). Mirrors bootstrap_client.yml's existing Jinja template
    exactly: same filename convention, same signed-vs-trusted branching,
    same space-joined components list.

    filename includes BOTH environment_name and content_view_name — one
    environment can have any number of content views assigned to it
    (EnvironmentContentView, models.py), so environment_name alone is no
    longer unique enough to avoid one assignment's file overwriting
    another's.
    """
    filename = f"groundctl-{environment_name}-{content_view_name}.list"
    base = f"{published_repo_base_url}/{publish_prefix}/"
    components_str = " ".join(components)

    if gpg_key_id is not None:
        keyring_filename = f"groundctl-{environment_name}-{content_view_name}.gpg"
        contents = f"deb [signed-by=/etc/apt/keyrings/{keyring_filename}] {base} {release} {components_str}\n"
        return AptSource(filename=filename, contents=contents, keyring_filename=keyring_filename)

    contents = f"deb [trusted=yes] {base} {release} {components_str}\n"
    return AptSource(filename=filename, contents=contents, keyring_filename=None)


def export_gpg_public_key(gpg_key_id: str) -> str | None:
    """Exports an ASCII-armored public key from the PRIMARY's own local
    GPG keyring — same subprocess call
    lifecycle_environments.get_environment_gpg_key already makes (kept in
    that router too, unchanged, for its own GET .../gpg-key endpoint;
    this is the shared implementation both it and beacon.py's checkin now
    call instead of two copies of the same subprocess.run). Returns None
    on any failure (key not present, gpg not installed, non-zero exit) —
    callers treat that as "couldn't get the key," same posture as the
    existing endpoint's 502.
    """
    proc = subprocess.run(
        ["gpg", "--export", "--armor", gpg_key_id],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout.decode("utf-8")


def resolve_environment_components(environment_current_version_snapshots: list[dict] | None) -> list[str]:
    """Same fallback/dedup logic bootstrap_task already had inline:
    ["main"] when the environment has never published a version yet,
    otherwise the unique, order-preserving list of components actually
    present in its current ContentViewVersion's snapshots.
    """
    if not environment_current_version_snapshots:
        return ["main"]
    seen: set[str] = set()
    components: list[str] = []
    for entry in environment_current_version_snapshots:
        component = entry["component"]
        if component not in seen:
            seen.add(component)
            components.append(component)
    return components
