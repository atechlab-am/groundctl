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
    assert body["description"] is None


def test_create_content_view_with_description(client, operator_token):
    repo = _create_repo(client, operator_token, "described-cv-repo")
    r = client.post(
        "/content-views",
        json={
            "name": "described-cv",
            "description": "Base packages for Ubuntu 22.04 servers",
            "repository_ids": [repo["id"]],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["description"] == "Base packages for Ubuntu 22.04 servers"

    get_r = client.get(f"/content-views/{body['id']}", headers=auth_headers(operator_token))
    assert get_r.json()["description"] == "Base packages for Ubuntu 22.04 servers"


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


def test_list_content_view_versions_has_v1_after_create(client, operator_token, viewer_token):
    # Creating a content view now cuts version 1 immediately, from the
    # member repositories' current state — matches Satellite, where a
    # newly created content view already has an initial version rather
    # than existing as an empty shell.
    repo = _create_repo(client, operator_token, "versions-v1-repo")
    cv = client.post(
        "/content-views",
        json={"name": "versions-v1-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    versions = r.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1


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


def test_create_content_view_cuts_version_1_immediately(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.get_snapshot_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"},
        {"Package": "curl", "Version": "7.81.0-1", "Architecture": "amd64"},
    ]
    repo = _create_repo(client, operator_token, "create-cuts-v1-repo")

    r = client.post(
        "/content-views",
        json={"name": "create-cuts-v1-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    cv = r.json()

    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    assert versions_r.status_code == 200, versions_r.text
    versions = versions_r.json()
    assert len(versions) == 1
    version = versions[0]
    assert version["version"] == 1
    assert len(version["snapshots"]) == 1
    assert version["snapshots"][0]["component"] == "main"
    # Counted from get_snapshot_packages (the final, post-filter snapshot),
    # not get_mirror_packages (the source mirror) — this content view has
    # no filters, but the two are deliberately given different package
    # lists here to prove the count comes from the right call.
    assert version["package_count"] == 2


def test_publish_content_view_cuts_new_version_after_repo_change(client, operator_token, mock_aptly):
    # Version 1 already exists from creation (see
    # test_create_content_view_cuts_version_1_immediately) — this proves
    # an explicit publish afterward still cuts version 2 when the
    # repository's content has genuinely changed since then.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "publish-repo")
    cv = client.post(
        "/content-views",
        json={"name": "publish-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-7", "Architecture": "amd64"}
    ]
    r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version_cut"] is True
    assert body["content_view_version"]["version"] == 2


def test_publish_content_view_package_count_not_double_counted_across_components(client, operator_token, mock_aptly):
    """A repo with multiple components reuses the same snapshot_name across
    several `snapshots` entries — package_count must sum unique snapshots
    once, not once per (repo, component) entry.
    """
    mock_aptly.get_mirror_packages.return_value = [{"Package": "nginx", "Version": "1.0", "Architecture": "amd64"}]
    mock_aptly.get_snapshot_packages.return_value = [
        {"Package": "nginx", "Version": "1.0", "Architecture": "amd64"},
        {"Package": "curl", "Version": "7.0", "Architecture": "amd64"},
        {"Package": "vim", "Version": "9.0", "Architecture": "amd64"},
    ]
    repo_r = client.post(
        "/repositories",
        json={
            "name": "multi-component-repo",
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distribution": "jammy",
            "components": ["main", "universe"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    )
    assert repo_r.status_code == 201, repo_r.text
    repo = repo_r.json()
    cv_r = client.post(
        "/content-views",
        json={"name": "multi-component-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert cv_r.status_code == 201, cv_r.text
    cv = cv_r.json()

    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    versions = versions_r.json()
    assert len(versions) == 1
    version = versions[0]
    # Two components -> two snapshots entries, but both share the same
    # underlying snapshot_name (one repo, no filters) -> counted once.
    assert len(version["snapshots"]) == 2
    assert version["package_count"] == 3


def test_publish_content_view_idempotent_when_unchanged(client, operator_token, mock_aptly):
    # Version 1 already exists from creation — an explicit publish right
    # after, with nothing changed, must be a no-op returning that same v1.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "publish-repo2")
    cv = client.post(
        "/content-views",
        json={"name": "publish-cv2", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    assert r.json()["version_cut"] is False
    assert r.json()["content_view_version"]["version"] == 1


def test_publish_content_view_force_cuts_new_version_even_when_unchanged(client, operator_token, mock_aptly):
    # Version 1 already exists from creation — force=True must cut version
    # 2 anyway even though nothing changed since then.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "publish-force-repo")
    cv = client.post(
        "/content-views",
        json={"name": "publish-force-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.post(
        f"/content-views/{cv['id']}/publish", json={"force": True}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    assert r.json()["version_cut"] is True
    assert r.json()["content_view_version"]["version"] == 2

    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    assert [v["version"] for v in versions_r.json()] == [2, 1]


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


# ---------------------------------------------------------------------------
# PATCH /content-views/{id}/versions/{version_id}
# ---------------------------------------------------------------------------


def test_set_version_description_as_operator(client, operator_token):
    repo = _create_repo(client, operator_token, "desc-repo")
    cv = client.post(
        "/content-views",
        json={"name": "desc-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]
    assert version["description"] is None

    r = client.patch(
        f"/content-views/{cv['id']}/versions/{version['id']}",
        json={"description": "Approved for prod rollout 2026-08"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] == "Approved for prod rollout 2026-08"
    # Version number, snapshots, content_hash all untouched — annotation only.
    assert body["version"] == version["version"]
    assert body["content_hash"] == version["content_hash"]

    # Persisted, not just echoed back.
    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    assert versions_r.json()[0]["description"] == "Approved for prod rollout 2026-08"


def test_set_version_description_can_be_cleared(client, operator_token):
    repo = _create_repo(client, operator_token, "desc-clear-repo")
    cv = client.post(
        "/content-views",
        json={"name": "desc-clear-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    client.patch(
        f"/content-views/{cv['id']}/versions/{version['id']}",
        json={"description": "temporary note"},
        headers=auth_headers(operator_token),
    )
    r = client.patch(
        f"/content-views/{cv['id']}/versions/{version['id']}",
        json={"description": None},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] is None


def test_set_version_description_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "desc-viewer-repo")
    cv = client.post(
        "/content-views",
        json={"name": "desc-viewer-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    r = client.patch(
        f"/content-views/{cv['id']}/versions/{version['id']}",
        json={"description": "should not work"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_set_version_description_content_view_not_found(client, operator_token):
    r = client.patch(
        "/content-views/00000000-0000-0000-0000-000000000000/versions/00000000-0000-0000-0000-000000000000",
        json={"description": "x"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_set_version_description_version_not_found(client, operator_token):
    repo = _create_repo(client, operator_token, "desc-404-repo")
    cv = client.post(
        "/content-views",
        json={"name": "desc-404-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()

    r = client.patch(
        f"/content-views/{cv['id']}/versions/00000000-0000-0000-0000-000000000000",
        json={"description": "x"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_set_version_description_wrong_content_view_404s(client, operator_token):
    """A version belonging to content-view A must not be editable by
    addressing it through content-view B's URL — same isolation pattern
    used elsewhere (e.g. filters, beacon tokens)."""
    repo_a = _create_repo(client, operator_token, "desc-cv-a-repo")
    repo_b = _create_repo(client, operator_token, "desc-cv-b-repo")
    cv_a = client.post(
        "/content-views",
        json={"name": "desc-cv-a", "repository_ids": [repo_a["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    cv_b = client.post(
        "/content-views",
        json={"name": "desc-cv-b", "repository_ids": [repo_b["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    version_a = client.get(f"/content-views/{cv_a['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    r = client.patch(
        f"/content-views/{cv_b['id']}/versions/{version_a['id']}",
        json={"description": "should not apply"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


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


def test_create_content_view_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    """Creation now cuts version 1 in the same request (see
    test_create_content_view_cuts_version_1_immediately) — if aptly is
    unreachable at that moment, the whole creation must fail rather than
    leaving a content view with zero versions to promote.
    """
    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            repo = _create_repo(c, token, "create-unreachable-repo")
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(
                "/content-views",
                json={"name": "create-unreachable-cv", "repository_ids": [repo["id"]]},
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


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
