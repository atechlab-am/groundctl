"""httpx wrapper that attaches a Bearer access token to every request.

Auth model (see app/routers/auth.py):
  - Access tokens are short-lived (15 min default) and NEVER persisted —
    they live only in memory for the duration of one CLI invocation.
  - Refresh tokens are single-use/rotating: calling POST /auth/refresh
    revokes the presented token as a side effect and returns a brand-new
    one. This means the CLI MUST persist the newly-returned refresh token
    to disk immediately after a successful refresh, before doing anything
    else — if the process dies (or the next command runs) before that
    write happens, the old token is already revoked server-side and the
    user is locked out with no way to refresh again short of logging in.

Each CLI invocation performs exactly one refresh (on construction), then
uses the resulting access token for every request made during that
invocation. There is no retry-on-401 loop — if refresh fails, we fail fast
with a clear "not logged in" message rather than looping.
"""

from __future__ import annotations

import httpx

from groundctl_cli.config import Config, load_config, save_config
from groundctl_cli.errors import GroundctlError, error_from_response

NOT_LOGGED_IN_MESSAGE = "not logged in — run `groundctl auth login`"


class GroundctlClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config if config is not None else load_config()
        if not self.config.api_url:
            raise GroundctlError(NOT_LOGGED_IN_MESSAGE)

        self._http = httpx.Client(base_url=self.config.api_url, timeout=30.0)
        self._access_token: str | None = None

    # -- auth bootstrap ----------------------------------------------------

    def ensure_authenticated(self) -> None:
        """Refreshes once, persisting the rotated refresh token immediately
        on success. Called by every command except `auth login` itself
        before making its real API call."""
        if not self.config.refresh_token:
            raise GroundctlError(NOT_LOGGED_IN_MESSAGE)

        try:
            response = self._http.post(
                "/auth/refresh", json={"refresh_token": self.config.refresh_token}
            )
        except httpx.RequestError as exc:
            raise GroundctlError(f"could not reach {self.config.api_url}: {exc}") from exc

        if response.status_code == 429:
            # /auth/refresh is rate-limited server-side (5/minute) — the
            # stored refresh token is still valid and NOT consumed (the
            # rate limiter runs before the handler), so this is not a "log
            # in again" situation, just a "wait a moment" one. Distinguish
            # it from a genuine auth failure rather than misreporting it as
            # "not logged in".
            raise GroundctlError(
                "rate limited by the API (too many auth/refresh calls in the last minute) — wait a moment and retry"
            )

        if response.status_code != 200:
            # Old token is now presumed dead (expired/revoked/already used).
            # No retry loop — surface a clean message and let the user
            # re-authenticate explicitly.
            raise GroundctlError(NOT_LOGGED_IN_MESSAGE)

        body = response.json()
        self._access_token = body["access_token"]

        # Critical: persist the rotated refresh token BEFORE returning, so
        # every subsequent command (and any retry of this one) uses the new
        # token. The just-used token is already revoked server-side.
        self.config.refresh_token = body["refresh_token"]
        save_config(self.config)

    def login(self, username: str, password: str) -> None:
        try:
            response = self._http.post(
                "/auth/login", data={"username": username, "password": password}
            )
        except httpx.RequestError as exc:
            raise GroundctlError(f"could not reach {self.config.api_url}: {exc}") from exc

        if response.status_code != 200:
            raise GroundctlError(error_from_response(response))

        body = response.json()
        self._access_token = body["access_token"]
        # Only the refresh token is persisted — never the access token.
        self.config.refresh_token = body["refresh_token"]
        save_config(self.config)

    def logout(self) -> None:
        if self.config.refresh_token:
            try:
                self._http.post("/auth/logout", json={"refresh_token": self.config.refresh_token})
            except httpx.RequestError:
                # Best-effort server-side revoke — clear local state regardless.
                pass
        self.config.refresh_token = None
        save_config(self.config)

    # -- generic request helper --------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: dict | None = None,
    ) -> httpx.Response:
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        # Drop None-valued query params rather than sending "field=None".
        clean_params = None
        if params is not None:
            clean_params = {k: v for k, v in params.items() if v is not None}

        try:
            response = self._http.request(
                method, path, json=json, params=clean_params, headers=headers
            )
        except httpx.RequestError as exc:
            raise GroundctlError(f"could not reach {self.config.api_url}: {exc}") from exc

        if response.status_code >= 400:
            raise GroundctlError(error_from_response(response))
        return response

    def get(self, path: str, *, params: dict | None = None) -> httpx.Response:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json: object = None, params: dict | None = None) -> httpx.Response:
        return self.request("POST", path, json=json, params=params)

    def put(self, path: str, *, json: object = None, params: dict | None = None) -> httpx.Response:
        return self.request("PUT", path, json=json, params=params)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GroundctlClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
