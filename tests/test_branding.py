import io

import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _png_bytes() -> bytes:
    # Smallest valid PNG (1x1, transparent) — real magic bytes, not just
    # an arbitrary blob, in case content sniffing is ever added later.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d494844410000000100000001080600000"
        "01f15c4890000000a4944415478da6360000002000155537de7000000"
        "0049454e44ae426082"
    )


def test_get_branding_defaults_when_unconfigured(client, viewer_token):
    r = client.get("/branding", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["primary_color"] is None
    assert body["has_logo"] is False
    assert body["has_favicon"] is False
    assert body["updated_at"] is None


def test_get_branding_unauthenticated_ok(client):
    # No Authorization header — the login page and browser tab need this
    # to work before any session exists, same reasoning as the logo/
    # favicon image endpoints already being public.
    r = client.get("/branding")
    assert r.status_code == 200, r.text


def test_update_colors_as_admin(client, admin_token):
    r = client.put(
        "/branding/colors",
        json={"primary_color": "#0F6CBD", "accent_color": "#115EA3"},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["primary_color"] == "#0F6CBD"
    assert body["accent_color"] == "#115EA3"
    assert body["updated_at"] is not None


def test_update_colors_as_operator_forbidden(client, operator_token):
    r = client.put(
        "/branding/colors", json={"primary_color": "#0F6CBD"}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 403, r.text


def test_update_colors_rejects_invalid_hex(client, admin_token):
    r = client.put(
        "/branding/colors", json={"primary_color": "not-a-color"}, headers=auth_headers(admin_token)
    )
    assert r.status_code == 422, r.text


def test_upload_and_fetch_logo(client, admin_token):
    png = _png_bytes()
    r = client.post(
        "/branding/logo",
        files={"file": ("logo.png", io.BytesIO(png), "image/png")},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_logo"] is True

    # Fetching the actual image bytes requires no auth at all.
    fetched = client.get("/branding/logo")
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.content == png


def test_upload_favicon_as_operator_forbidden(client, operator_token):
    r = client.post(
        "/branding/favicon",
        files={"file": ("f.png", io.BytesIO(_png_bytes()), "image/png")},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 403, r.text


def test_upload_logo_rejects_unsupported_content_type(client, admin_token):
    r = client.post(
        "/branding/logo",
        files={"file": ("logo.svg", io.BytesIO(b"<svg></svg>"), "image/svg+xml")},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 422, r.text


def test_upload_logo_rejects_oversized_file(client, admin_token):
    oversized = b"\x00" * (2 * 1024 * 1024 + 1)
    r = client.post(
        "/branding/logo",
        files={"file": ("logo.png", io.BytesIO(oversized), "image/png")},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 413, r.text


def test_get_logo_404_when_unconfigured(client):
    r = client.get("/branding/logo")
    assert r.status_code == 404, r.text


def test_get_favicon_404_when_unconfigured(client):
    r = client.get("/branding/favicon")
    assert r.status_code == 404, r.text
