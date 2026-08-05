"""GroundctlClient tests against httpx.MockTransport — no real network or
backend. Focus: the refresh-token-rotation persistence property described
in the task spec (every command refreshes once, and the rotated refresh
token must be written to disk immediately, before the real call is made).
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def modules(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDCTL_CONFIG_DIR", str(tmp_path / "groundctl"))
    for name in list(sys.modules):
        if name.startswith("groundctl_cli"):
            del sys.modules[name]
    from groundctl_cli import client as client_module
    from groundctl_cli import config as config_module
    from groundctl_cli import errors as errors_module

    return client_module, config_module, errors_module


def _install_transport(client_module, handler) -> None:
    """Monkeypatch GroundctlClient to build its httpx.Client with a
    MockTransport instead of hitting the network. Mirrors the real
    __init__'s base_url = f"{api_url}/api" (see client.py) rather than just
    api_url — otherwise these tests would keep passing even if that /api
    prefixing broke, since the handler assertions below check
    request.url.path against un-prefixed paths like "/auth/refresh"."""
    original_init = client_module.GroundctlClient.__init__

    def patched_init(self, config=None):
        self.config = config if config is not None else client_module.load_config()
        if not self.config.api_url:
            raise client_module.GroundctlError(client_module.NOT_LOGGED_IN_MESSAGE)
        self._http = httpx.Client(
            base_url=f"{self.config.api_url.rstrip('/')}/api",
            transport=httpx.MockTransport(handler),
            timeout=30.0,
        )
        self._access_token = None

    client_module.GroundctlClient.__init__ = patched_init
    return original_init


def test_ensure_authenticated_persists_rotated_refresh_token(modules, tmp_path):
    client_module, config_module, _ = modules

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/refresh":
            calls.append(request)
            body = request.read()
            import json

            presented = json.loads(body)["refresh_token"]
            assert presented == "old-token"  # only ever called with the current stored token
            return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "new-token", "token_type": "bearer"})
        raise AssertionError(f"unexpected request to {request.url.path}")

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="old-token")
    config_module.save_config(config)

    client = client_module.GroundctlClient(config)
    client.ensure_authenticated()

    assert len(calls) == 1
    assert client._access_token == "access-1"

    # The critical property: the rotated token must already be on disk,
    # not just in memory, by the time ensure_authenticated returns.
    reloaded = config_module.load_config()
    assert reloaded.refresh_token == "new-token"


def test_three_commands_in_a_row_never_reuse_a_revoked_token(modules):
    """Simulates the exact failure mode described in the task: if the CLI
    doesn't persist the rotated token before returning, the second command
    in a session reuses the already-revoked token and 401s. This drives a
    fresh GroundctlClient (as a real new CLI invocation would) through
    ensure_authenticated() three times against a fake server that revokes
    each refresh token the instant it's used - exactly like the real
    backend's consume_refresh_token."""
    client_module, config_module, _ = modules

    server_valid_token = {"value": "token-0"}
    revoked = set()

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.url.path == "/api/auth/refresh"
        presented = json.loads(request.read())["refresh_token"]
        if presented in revoked or presented != server_valid_token["value"]:
            return httpx.Response(401, json={"detail": "refresh token invalid or already used"})
        revoked.add(presented)
        new_token = f"token-{len(revoked)}"
        server_valid_token["value"] = new_token
        return httpx.Response(200, json={"access_token": f"access-{len(revoked)}", "refresh_token": new_token, "token_type": "bearer"})

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="token-0")
    config_module.save_config(config)

    for _ in range(3):
        # Each iteration re-reads config from disk, exactly like a fresh
        # CLI process invocation would.
        fresh_config = config_module.load_config()
        client = client_module.GroundctlClient(fresh_config)
        client.ensure_authenticated()  # must not raise


def test_ensure_authenticated_no_stored_token_fails_clean(modules):
    client_module, config_module, _ = modules

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the API when there's no stored refresh token")

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token=None)
    client = client_module.GroundctlClient(config)

    with pytest.raises(client_module.GroundctlError, match="not logged in"):
        client.ensure_authenticated()


def test_ensure_authenticated_expired_refresh_fails_clean_no_retry_loop(modules):
    client_module, config_module, _ = modules

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"detail": "refresh token expired"})

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="expired-token")
    client = client_module.GroundctlClient(config)

    with pytest.raises(client_module.GroundctlError, match="not logged in"):
        client.ensure_authenticated()

    assert call_count["n"] == 1  # no retry loop


def test_ensure_authenticated_rate_limited_is_distinguished_from_logged_out(modules):
    client_module, config_module, _ = modules

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "rate limit exceeded"})

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="some-token")
    client = client_module.GroundctlClient(config)

    with pytest.raises(client_module.GroundctlError, match="rate limited"):
        client.ensure_authenticated()


def test_login_stores_only_refresh_token_not_access_token(modules):
    client_module, config_module, _ = modules

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/auth/login"
        return httpx.Response(
            200, json={"access_token": "super-secret-access", "refresh_token": "refresh-abc", "token_type": "bearer"}
        )

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token=None)
    client = client_module.GroundctlClient(config)
    client.login("alice", "hunter2")

    on_disk = config_module.load_config()
    assert on_disk.refresh_token == "refresh-abc"
    # The access token must never be persisted to disk.
    raw_file = config_module.CONFIG_FILE.read_text()
    assert "super-secret-access" not in raw_file


def test_request_attaches_bearer_token(modules):
    client_module, config_module, _ = modules

    seen_auth_header = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/repositories":
            seen_auth_header["value"] = request.headers.get("authorization")
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path {request.url.path}")

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="t")
    client = client_module.GroundctlClient(config)
    client._access_token = "the-access-token"
    client.get("/repositories")

    assert seen_auth_header["value"] == "Bearer the-access-token"


def test_error_response_raises_groundctl_error_with_normalized_message(modules):
    client_module, config_module, errors_module = modules

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body", "name"], "msg": "field required", "type": "missing"}]})

    _install_transport(client_module, handler)

    config = config_module.Config(api_url="https://groundctl.test", refresh_token="t")
    client = client_module.GroundctlClient(config)
    client._access_token = "x"

    with pytest.raises(errors_module.GroundctlError, match="name: field required"):
        client.get("/repositories")
