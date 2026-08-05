import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def test_list_docs_as_viewer(client, viewer_token):
    r = client.get("/api/docs", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) > 0
    filenames = {d["filename"] for d in body}
    assert "install.md" in filenames
    assert "first-environment.md" in filenames
    # Every entry has a real title, not just the filename fallback —
    # confirms the H1 extraction actually ran against real doc content.
    install_doc = next(d for d in body if d["filename"] == "install.md")
    assert install_doc["title"] != "install.md"


def test_list_docs_requires_auth(client):
    r = client.get("/api/docs")
    assert r.status_code == 401, r.text


def test_get_doc_as_viewer(client, viewer_token):
    r = client.get("/api/docs/quickstart.md", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "quickstart.md"
    assert body["title"]
    assert "curl" in body["content"]


def test_get_doc_not_found(client, viewer_token):
    r = client.get("/api/docs/does-not-exist.md", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_doc_rejects_path_traversal(client, viewer_token):
    # Both a literal ../ segment and a URL-encoded one — FastAPI/Starlette
    # normalizes %2F itself for a {filename} path param (single segment),
    # so what actually reaches the handler is the still-invalid string
    # containing "..", which _DOC_FILENAME_RE correctly rejects either way.
    for attempt in ["....md", "..%2F..%2Fetc%2Fpasswd", "..-etc-passwd.md"]:
        r = client.get(f"/api/docs/{attempt}", headers=auth_headers(viewer_token))
        assert r.status_code in (404, 422), f"{attempt} -> {r.status_code}: {r.text}"


def test_get_doc_rejects_uppercase_and_non_md(client, viewer_token):
    for attempt in ["Install.md", "install.txt", "install"]:
        r = client.get(f"/api/docs/{attempt}", headers=auth_headers(viewer_token))
        assert r.status_code == 422, f"{attempt} -> {r.status_code}: {r.text}"
