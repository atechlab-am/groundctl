import re

import httpx

from app.config import settings

APTLY_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class AptlyError(Exception):
    """Raised for both HTTP error responses and transport failures (connection
    refused, timeout, DNS) talking to aptly. Routers catch this and re-raise as
    HTTPException(502) — this is the only exception type that should ever
    escape AptlyClient.
    """


def _validate_name(value: str) -> str:
    if not APTLY_NAME_RE.fullmatch(value):
        raise AptlyError(f"invalid aptly object name: {value!r}")
    return value


class AptlyClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self._client = httpx.Client(base_url=base_url or settings.aptly_api_url, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise AptlyError(
                f"aptly returned {exc.response.status_code} for {method} {path}: {exc.response.text}"
            ) from exc
        except httpx.TransportError as exc:
            raise AptlyError(f"aptly unreachable: {method} {path}: {exc}") from exc

    @staticmethod
    def _json_or_empty(response: httpx.Response) -> dict | list:
        # aptly's behavior on "already up to date" / no-op operations varies
        # by version — some return the object, some return 204 with an empty
        # body (see docs/limitations.md). Never let json() crash on that.
        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def _json_object_or_empty(response: httpx.Response) -> dict:
        # Same as _json_or_empty, narrowed for the endpoints below whose
        # documented aptly response shape is always a single JSON object,
        # never a bare array — asserting that here (rather than widening
        # every caller's return type to dict | list) keeps the honest
        # per-endpoint contract instead of pushing an impossible case onto
        # callers that never need to handle it.
        result = AptlyClient._json_or_empty(response)
        if not isinstance(result, dict):
            raise AptlyError(f"expected a JSON object from aptly, got {type(result).__name__}")
        return result

    # -- health / maintenance ------------------------------------------------

    def ping(self) -> None:
        """Raises AptlyError if aptly is unreachable or returns an error —
        used by GET /health (app/main.py). GET /api/version is aptly's
        lightest endpoint; this call's only purpose is confirming
        reachability, the response body is unused.
        """
        self._request("GET", "/api/version")

    def cleanup_db(self) -> dict:
        """Wraps aptly's POST /api/db/cleanup — removes unreferenced package
        files from the pool (snapshots/mirrors that no longer reference
        them). Called by the weekly scheduled_aptly_maintenance task
        (app/tasks.py); the pool grows unbounded otherwise (see
        docs/limitations.md).
        """
        response = self._request("POST", "/api/db/cleanup", timeout=1800.0)
        return self._json_object_or_empty(response)

    # -- mirrors ------------------------------------------------------------

    def create_mirror(
        self,
        name: str,
        archive_url: str,
        distribution: str,
        components: list[str],
        architectures: list[str],
    ) -> dict:
        _validate_name(name)
        _validate_name(distribution)
        for component in components:
            _validate_name(component)
        response = self._request(
            "POST",
            "/api/mirrors",
            json={
                "Name": name,
                "ArchiveURL": archive_url,
                "Distribution": distribution,
                "Components": components,
                "Architectures": architectures,
                # Deliberately omit Keyrings: aptly falls back to gpgv's
                # default trust store (~/.gnupg/trustedkeys.gpg for the
                # invoking user — see scripts/lib/aptly.sh's
                # import_aptly_trustedkeys) when it's absent. Real
                # bug found and fixed: passing Keyrings here does NOT
                # supplement that default lookup, it REPLACES it — so
                # hardcoding [debian, ubuntu] here silently broke
                # verification for any archive signed by a key outside those
                # two keyrings (e.g. a third-party repo like Docker's),
                # even when that key was correctly imported into
                # trustedkeys.gpg. Confirmed by testing the same mirror
                # create call with and without this field against a live
                # aptly 1.6.3 instance.
            },
        )
        return self._json_object_or_empty(response)

    def delete_mirror(self, name: str) -> None:
        """Deletes an aptly mirror outright. aptly itself refuses this
        (returns 409) if any snapshot still references the mirror's package
        pool — callers should still check for a ContentView reference first
        (routers/repositories.py's delete_repository) since aptly's own
        snapshot-level check doesn't know about groundctl's ContentView
        concept, and a mirror can exist with zero snapshots yet still be
        wrong to delete out from under a caller mid-sync.

        Extended timeout: confirmed live against a real mirror with a full
        Ubuntu-scale package set — deleting checks/detaches pool references
        for every package the mirror holds, the same class of operation as
        sync_mirror/publish_snapshot below. The default 30s client timeout
        genuinely isn't enough; this was surfaced as "aptly unreachable:
        DELETE /api/mirrors/<name>: timed out" against a live instance — a
        TransportError timeout, not aptly actually being unreachable.
        Raised again to match sync_mirror's 6h ceiling — delete_mirror
        always runs inside delete_repository_task (a Celery job, see
        app/tasks.py), same no-one's-actually-waiting reasoning.
        """
        _validate_name(name)
        self._request("DELETE", f"/api/mirrors/{name}", timeout=21600.0)

    def sync_mirror(self, name: str) -> dict:
        _validate_name(name)
        # First-run syncs download real package files and can take many
        # minutes (docs/limitations.md) — much longer than the default
        # client timeout used for quick metadata calls. Real case hit
        # live: a full jammy mirror (~100GB) took just over 30 minutes and
        # tripped the previous 1800s timeout exactly at that mark — the
        # sync was genuinely still progressing, not stuck. sync_mirror
        # always runs inside sync_repository_task (a Celery job, see
        # app/tasks.py) with no HTTP client actually waiting on this call,
        # so there's no real cost to a generous ceiling — 6h comfortably
        # covers a much larger mirror on a slow connection without
        # papering over an actually-hung aptly (which would eventually
        # still time out and get reported, just later).
        response = self._request("PUT", f"/api/mirrors/{name}", timeout=21600.0)
        return self._json_object_or_empty(response)

    def get_mirror_packages(self, name: str) -> list[dict]:
        _validate_name(name)
        # Without format=details, aptly returns bare package-key strings
        # (e.g. "Pamd64 name version hash"), not objects with Name/Version/
        # Architecture fields — every caller here needs the structured form.
        response = self._request("GET", f"/api/mirrors/{name}/packages", params={"format": "details"})
        return response.json() if response.content else []

    def get_mirror_size_bytes(self, name: str) -> int:
        """Sum of each package's Size field (bytes, from the .deb's control
        data) across a mirror's current package set — the actual on-disk
        footprint of the .deb files aptly has downloaded, not counting
        Packages/Release metadata. Used after sync to record
        Repository.size_bytes. Missing/non-numeric Size on an individual
        package is treated as 0 rather than failing the whole sum — better
        an undercount than a 502 on an otherwise-successful sync.

        Real bug found live: aptly's ?format=details response encodes Size
        as a JSON STRING ("84924"), not a number — confirmed against a real
        aptly 1.6.3 instance's actual output. The original `isinstance(size,
        int)` check therefore rejected every package's size unconditionally
        and this always summed to 0, silently, no error — every repo's
        size_bytes has been wrong since this was written. Every other
        control field this client reads (Version, Architecture, etc.) is
        also a string in aptly's own output, for the same reason (it's
        parsed straight from a .deb's plain-text control file) — Size is
        the one field this code needs as a number, so it's the one that
        needs converting.
        """
        total = 0
        for package in self.get_mirror_packages(name):
            size = package.get("Size")
            if isinstance(size, int):
                total += size
            elif isinstance(size, str) and size.isdigit():
                total += int(size)
        return total

    # -- snapshots ------------------------------------------------------------

    def create_snapshot_from_mirror(self, mirror_name: str, snapshot_name: str) -> dict:
        _validate_name(mirror_name)
        _validate_name(snapshot_name)
        # Cutting a snapshot from a large mirror can take minutes — same
        # rationale as sync_mirror's extended timeout.
        response = self._request(
            "POST",
            f"/api/mirrors/{mirror_name}/snapshots",
            json={"Name": snapshot_name},
            timeout=1800.0,
        )
        return self._json_object_or_empty(response)

    def get_snapshot_packages(self, snapshot_name: str) -> list[dict]:
        _validate_name(snapshot_name)
        response = self._request(
            "GET", f"/api/snapshots/{snapshot_name}/packages", params={"format": "details"}
        )
        return response.json() if response.content else []

    # -- publish ------------------------------------------------------------

    def publish_exists(self, prefix: str) -> bool:
        _validate_name(prefix)
        response = self._request("GET", "/api/publish")
        entries = response.json() if response.content else []
        for entry in entries:
            if entry.get("Prefix") == prefix:
                return True
        return False

    def publish_snapshot(
        self, prefix: str, distribution: str, sources: list[tuple[str, str]], gpg_key_id: str | None = None
    ) -> dict:
        """sources: list of (snapshot_name, component) pairs — one per
        (repository, component) contributing to this publish. A ContentView
        aggregating N repositories, each with M components, produces N*M
        pairs here, all sharing one publish prefix.

        gpg_key_id: the LifecycleEnvironment's configured signing key, if
        any (see docs/gpg-signing.md). None means unsigned — an explicit
        opt-in via LifecycleEnvironmentCreate.allow_unsigned, not a
        hardcoded default.
        """
        _validate_name(prefix)
        _validate_name(distribution)
        for snapshot_name, component in sources:
            _validate_name(snapshot_name)
            _validate_name(component)
        # Publishing hardlinks/copies each snapshot's package pool into the
        # published tree — can take minutes for a large snapshot, same
        # rationale as sync_mirror's extended timeout.
        response = self._request(
            "POST",
            f"/api/publish/{prefix}",
            json={
                "SourceKind": "snapshot",
                "Sources": [{"Name": name, "Component": component} for name, component in sources],
                "Distribution": distribution,
                "Signing": {"Skip": gpg_key_id is None, "GpgKey": gpg_key_id},
            },
            timeout=1800.0,
        )
        return self._json_object_or_empty(response)

    def switch_publish(
        self, prefix: str, distribution: str, sources: list[tuple[str, str]], gpg_key_id: str | None = None
    ) -> dict:
        """sources: same (snapshot_name, component) pairs as publish_snapshot."""
        _validate_name(prefix)
        _validate_name(distribution)
        for snapshot_name, component in sources:
            _validate_name(snapshot_name)
            _validate_name(component)
        response = self._request(
            "PUT",
            f"/api/publish/{prefix}/{distribution}",
            json={
                "Snapshots": [{"Component": component, "Name": name} for name, component in sources],
                # Must match publish_snapshot's Signing config — aptly
                # defaults to signing on update/switch even if the initial
                # publish was unsigned, and fails outright with no GPG key
                # configured. Pass the same gpg_key_id the environment was
                # originally published with.
                "Signing": {"Skip": gpg_key_id is None, "GpgKey": gpg_key_id},
            },
            timeout=1800.0,
        )
        return self._json_object_or_empty(response)

    def create_filtered_snapshot(self, source_snapshot_name: str, new_snapshot_name: str, query: str) -> dict:
        """Cut a filtered copy of an existing snapshot via aptly's snapshot
        filter endpoint. `query` is aptly's own package-query syntax (e.g.
        "Name (~ pattern)" to include, "!Name (~ pattern)" to exclude) — NOT
        a raw regex; callers must translate ContentViewFilter rows into this
        syntax before calling.

        UNVERIFIED against a live aptly instance — the request/response shape
        below is aptly's documented `POST /api/snapshots/:name/filter`
        contract, but (like ?format=details and the Package-vs-Name field
        naming) has not been confirmed against a running aptly 1.6.3 server
        the way the rest of this client has. Confirm before relying on this
        in production; see docs/limitations.md.
        """
        _validate_name(source_snapshot_name)
        _validate_name(new_snapshot_name)
        response = self._request(
            "POST",
            f"/api/snapshots/{source_snapshot_name}/filter",
            json={
                "Destination": new_snapshot_name,
                "Query": query,
                "WithDeps": False,
            },
            timeout=1800.0,
        )
        return self._json_object_or_empty(response)


def get_aptly_client() -> AptlyClient:
    return AptlyClient()
