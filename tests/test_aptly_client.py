import httpx
import pytest

from app.aptly_client import AptlyClient


def _client_with_packages(packages: list[dict]) -> AptlyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/mirrors/jammy/packages"
        return httpx.Response(200, json=packages)

    client = AptlyClient(base_url="http://aptly.test")
    client._client = httpx.Client(base_url="http://aptly.test", transport=httpx.MockTransport(handler))
    return client


def test_get_mirror_size_bytes_sums_string_size_field():
    # Real bug found live: aptly's ?format=details response encodes Size as
    # a JSON string ("84924"), not a number — confirmed against a real
    # aptly 1.6.3 instance. A prior version of this code only accepted a
    # Python int and silently summed to 0 for every real mirror.
    client = _client_with_packages(
        [
            {"Package": "a", "Size": "1000"},
            {"Package": "b", "Size": "2500"},
        ]
    )
    assert client.get_mirror_size_bytes("jammy") == 3500


def test_get_mirror_size_bytes_accepts_int_too():
    client = _client_with_packages([{"Package": "a", "Size": 1000}])
    assert client.get_mirror_size_bytes("jammy") == 1000


def test_get_mirror_size_bytes_skips_missing_or_malformed():
    client = _client_with_packages(
        [
            {"Package": "a", "Size": "1000"},
            {"Package": "b"},
            {"Package": "c", "Size": "not-a-number"},
            {"Package": "d", "Size": None},
        ]
    )
    assert client.get_mirror_size_bytes("jammy") == 1000


def test_get_mirror_size_bytes_empty_mirror():
    client = _client_with_packages([])
    assert client.get_mirror_size_bytes("jammy") == 0
