import gzip
import re

import httpx

# Apt archives publish a plain Apache/nginx-style autoindex at
# <archive_url>/dists/ — one <a href="name/"> per distribution directory.
# This is not an aptly API call (aptly has no "browse an archive" concept)
# so it goes over its own httpx client rather than AptlyClient.
_DIR_LINK_RE = re.compile(r'<a\s+href="([^"?][^"]*)/(?:")?"')

# Autoindex pages are small (a few KB even for archive.ubuntu.com's ~20
# distributions); cap generously to bound memory/time against a
# misbehaving or malicious archive_url without truncating a real one.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# A Packages.gz for a large component (e.g. Ubuntu's universe/amd64) can run
# tens of MB compressed. Cap well above that so a real archive is never
# truncated, but still bound against a misbehaving/malicious archive_url.
_MAX_PACKAGES_FILE_BYTES = 200 * 1024 * 1024

_SIZE_FIELD_RE = re.compile(rb"^Size:\s*(\d+)\s*$", re.MULTILINE)


class ArchiveProbeError(Exception):
    """Raised for both transport failures and unparseable responses probing
    an upstream archive's dists/ index. Routers catch this and re-raise as
    HTTPException(502) — same contract as AptlyError.
    """


def probe_distributions(archive_url: str, timeout: float = 15.0) -> list[str]:
    """Fetch <archive_url>/dists/ and return the distribution names found
    (e.g. ["jammy", "jammy-updates", "jammy-security", ...]), sorted.
    Read-only — never used to fetch package data, just the directory
    listing HTML.
    """
    url = archive_url.rstrip("/") + "/dists/"
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    raise ArchiveProbeError(f"response from {url} exceeded {_MAX_RESPONSE_BYTES} bytes")
                chunks.append(chunk)
            body = b"".join(chunks).decode("utf-8", errors="replace")
    except httpx.HTTPStatusError as exc:
        raise ArchiveProbeError(f"{url} returned {exc.response.status_code}") from exc
    except httpx.TransportError as exc:
        raise ArchiveProbeError(f"could not reach {url}: {exc}") from exc

    names = {
        match.group(1)
        for match in _DIR_LINK_RE.finditer(body)
        # Excludes the "Parent Directory" link (an absolute or ../ href,
        # e.g. "/ubuntu" or "..") and anything else that isn't a plain
        # child-directory name — real distribution names never contain "/".
        if match.group(1) and match.group(1) != ".." and "/" not in match.group(1)
    }
    if not names:
        raise ArchiveProbeError(f"no distributions found at {url} — is this a valid apt archive?")
    return sorted(names)


def estimate_repository_size_bytes(
    archive_url: str,
    distribution: str,
    components: list[str],
    architectures: list[str],
    timeout: float = 30.0,
) -> int:
    """Best-effort estimate of a not-yet-created mirror's size, computed
    before aptly ever touches it: for each (component, architecture) pair,
    fetch <archive_url>/dists/<distribution>/<component>/binary-<arch>/
    Packages.gz and sum every "Size:" control field found. This is the same
    number aptly's own sync will eventually reproduce (get_mirror_size_bytes
    in aptly_client.py, computed post-sync from real package data) — this
    function just reads the same upstream metadata early, without mirroring
    anything.

    Best-effort: a component/arch combination that 404s (e.g. an
    architecture the upstream distro doesn't publish for that component) is
    skipped rather than failing the whole estimate — probe callers want a
    number for what does exist, not a hard failure over one missing
    combination. Raises ArchiveProbeError only if every combination fails,
    since that means the archive_url/distribution itself is likely wrong.
    """
    base = archive_url.rstrip("/")
    total = 0
    any_succeeded = False
    last_error: Exception | None = None

    for component in components:
        for arch in architectures:
            packages_url = f"{base}/dists/{distribution}/{component}/binary-{arch}/Packages.gz"
            try:
                with httpx.stream("GET", packages_url, timeout=timeout, follow_redirects=True) as response:
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > _MAX_PACKAGES_FILE_BYTES:
                            raise ArchiveProbeError(f"response from {packages_url} exceeded size cap")
                        chunks.append(chunk)
                body = gzip.decompress(b"".join(chunks))
            except (httpx.HTTPStatusError, httpx.TransportError, gzip.BadGzipFile, OSError) as exc:
                last_error = exc
                continue

            any_succeeded = True
            total += sum(int(match.group(1)) for match in _SIZE_FIELD_RE.finditer(body))

    if not any_succeeded:
        raise ArchiveProbeError(
            f"could not fetch Packages data for {distribution} at {archive_url}"
            + (f": {last_error}" if last_error else "")
        )
    return total
