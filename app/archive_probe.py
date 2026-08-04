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
