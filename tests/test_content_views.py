import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _create_repo(client, operator_token, name="jammy-main"):
    r = client.post(
        "/repositories",
        json={
            "name": name,
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distribution": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_content_view_as_operator(client, operator_token):
    repo = _create_repo(client, operator_token)
    r = client.post(
        "/content-views",
        json={"name": "base-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "base-cv"
    assert body["repository_ids"] == [repo["id"]]


def test_create_content_view_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "viewer-forbidden-repo")
    r = client.post(
        "/content-views",
        json={"name": "cv-viewer", "repository_ids": [repo["id"]]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_create_content_view_duplicate_name_conflicts(client, operator_token):
    repo = _create_repo(client, operator_token, "dup-cv-repo")
    r1 = client.post(
        "/content-views",
        json={"name": "dup-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/content-views",
        json={"name": "dup-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 409, r2.text


def test_create_content_view_missing_repository_404s(client, operator_token):
    r = client.post(
        "/content-views",
        json={"name": "missing-repo-cv", "repository_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_list_content_view_versions_empty(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "versions-empty-repo")
    cv = client.post(
        "/content-views",
        json={"name": "versions-empty-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_content_view_versions_not_found(client, viewer_token):
    r = client.get(
        "/content-views/00000000-0000-0000-0000-000000000000/versions",
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 404, r.text


def test_create_content_view_filter_as_operator(client, operator_token):
    repo = _create_repo(client, operator_token, "filter-repo")
    cv = client.post(
        "/content-views",
        json={"name": "filter-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filter_type"] == "include"
    assert body["pattern"] == "nginx*"


def test_create_content_view_filter_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "filter-repo2")
    cv = client.post(
        "/content-views",
        json={"name": "filter-cv2", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_create_content_view_filter_not_found(client, operator_token):
    r = client.post(
        "/content-views/00000000-0000-0000-0000-000000000000/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_create_content_view_filter_errata_since_requires_iso_date(client, operator_token):
    repo = _create_repo(client, operator_token, "filter-repo3")
    cv = client.post(
        "/content-views",
        json={"name": "filter-cv3", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "errata_since", "pattern": "not-a-date"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 422, r.text


def test_publish_content_view_cuts_new_version(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "publish-repo")
    cv = client.post(
        "/content-views",
        json={"name": "publish-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version_cut"] is True
    assert body["content_view_version"]["version"] == 1
    assert len(body["content_view_version"]["snapshots"]) == 1
    assert body["content_view_version"]["snapshots"][0]["component"] == "main"


def test_publish_content_view_idempotent_when_unchanged(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "publish-repo2")
    cv = client.post(
        "/content-views",
        json={"name": "publish-cv2", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r1 = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert r1.status_code == 201, r1.text
    assert r1.json()["version_cut"] is True

    r2 = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert r2.status_code == 201, r2.text
    assert r2.json()["version_cut"] is False
    assert r2.json()["content_view_version"]["version"] == 1


def test_publish_content_view_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "publish-repo3")
    cv = client.post(
        "/content-views",
        json={"name": "publish-cv3", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_publish_content_view_not_found(client, operator_token):
    r = client.post(
        "/content-views/00000000-0000-0000-0000-000000000000/publish",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_publish_content_view_no_repositories_422(client, operator_token, db_session):
    from app.models import ContentView

    cv = ContentView(name="empty-cv")
    db_session.add(cv)
    db_session.commit()
    db_session.refresh(cv)

    r = client.post(f"/content-views/{cv.id}/publish", headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_list_content_views_as_viewer(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "list-cv-repo")
    client.post(
        "/content-views",
        json={"name": "list-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    r = client.get("/content-views", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert any(cv["name"] == "list-cv" for cv in r.json())


def test_get_content_view_as_viewer(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "get-cv-repo")
    cv = client.post(
        "/content-views",
        json={"name": "get-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.get(f"/content-views/{cv['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "get-cv"
    assert body["repository_ids"] == [repo["id"]]


def test_get_content_view_not_found(client, viewer_token):
    r = client.get("/content-views/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_delete_content_view_as_operator(client, operator_token):
    repo = _create_repo(client, operator_token, "delete-cv-repo")
    cv = client.post(
        "/content-views",
        json={"name": "delete-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(f"/content-views/{cv['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 204, r.text

    get_r = client.get(f"/content-views/{cv['id']}", headers=auth_headers(operator_token))
    assert get_r.status_code == 404, get_r.text


def test_delete_content_view_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "delete-cv-repo2")
    cv = client.post(
        "/content-views",
        json={"name": "delete-cv2", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(f"/content-views/{cv['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_delete_content_view_not_found(client, operator_token):
    r = client.delete("/content-views/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_delete_content_view_referenced_by_lifecycle_environment_conflicts(client, operator_token):
    repo = _create_repo(client, operator_token, "delete-cv-repo3")
    cv = client.post(
        "/content-views",
        json={"name": "delete-cv3", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    env_r = client.post(
        "/lifecycle-environments",
        json={
            "name": "delete-cv-env",
            "path_name": "delete-cv-path",
            "position": 0,
            "content_view_id": cv["id"],
            "distro": "ubuntu",
            "release": "jammy",
            "publish_prefix": "delete-cv-prefix",
            "allow_unsigned": True,
        },
        headers=auth_headers(operator_token),
    )
    assert env_r.status_code == 201, env_r.text

    r = client.delete(f"/content-views/{cv['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text
    assert "delete-cv-env" in r.json()["detail"]


def test_list_content_view_filters_empty(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "filters-empty-repo")
    cv = client.post(
        "/content-views",
        json={"name": "filters-empty-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.get(f"/content-views/{cv['id']}/filters", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_content_view_filters_not_found(client, viewer_token):
    r = client.get(
        "/content-views/00000000-0000-0000-0000-000000000000/filters",
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 404, r.text


def test_list_content_view_filters_after_create(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "filters-list-repo")
    cv = client.post(
        "/content-views",
        json={"name": "filters-list-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    )

    r = client.get(f"/content-views/{cv['id']}/filters", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["pattern"] == "nginx*"


def test_delete_content_view_filter_as_operator(client, operator_token):
    repo = _create_repo(client, operator_token, "delete-filter-repo")
    cv = client.post(
        "/content-views",
        json={"name": "delete-filter-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    content_filter = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(
        f"/content-views/{cv['id']}/filters/{content_filter['id']}", headers=auth_headers(operator_token)
    )
    assert r.status_code == 204, r.text

    list_r = client.get(f"/content-views/{cv['id']}/filters", headers=auth_headers(operator_token))
    assert list_r.json() == []


def test_delete_content_view_filter_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "delete-filter-repo2")
    cv = client.post(
        "/content-views",
        json={"name": "delete-filter-cv2", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    content_filter = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(
        f"/content-views/{cv['id']}/filters/{content_filter['id']}", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 403, r.text


def test_delete_content_view_filter_not_found(client, operator_token):
    repo = _create_repo(client, operator_token, "delete-filter-repo3")
    cv = client.post(
        "/content-views",
        json={"name": "delete-filter-cv3", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(
        f"/content-views/{cv['id']}/filters/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_delete_content_view_filter_wrong_content_view_404s(client, operator_token):
    repo = _create_repo(client, operator_token, "delete-filter-repo4")
    cv1 = client.post(
        "/content-views",
        json={"name": "delete-filter-cv4a", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    cv2 = client.post(
        "/content-views",
        json={"name": "delete-filter-cv4b", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    content_filter = client.post(
        f"/content-views/{cv1['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    ).json()

    r = client.delete(
        f"/content-views/{cv2['id']}/filters/{content_filter['id']}", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_publish_content_view_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            repo = _create_repo(c, token, "publish-repo-unreachable")
            cv = c.post(
                "/content-views",
                json={"name": "publish-cv-unreachable", "repository_ids": [repo["id"]]},
                headers=auth_headers(token),
            ).json()
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(token))
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()
