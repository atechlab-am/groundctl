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


# ---------------------------------------------------------------------------
# POST /content-views/{id}/publish-and-promote
# ---------------------------------------------------------------------------


def _create_env(client, operator_token, cv, name="env", path_name="path", position=0, publish_prefix="prefix", prior=None):
    # path_name/position/content_view_id/publish_prefix are no longer
    # creation-time fields (see LifecycleEnvironmentCreate) — deliberately
    # NOT auto-promoted here (unlike other test files' _create_env
    # helpers) since several tests in this file specifically need an
    # unpromoted environment (e.g. path-order enforcement, delete-guard
    # tests that promote explicitly at the point they need it). Pass
    # `prior` (another env dict) to chain into an existing path instead
    # of starting a new one at position 0. cv/path_name/position/
    # publish_prefix args are accepted for call-site compatibility but
    # only `prior` and `name` actually affect anything now.
    payload = {"name": name}
    if prior is not None:
        payload["prior_environment_id"] = prior["id"]
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    return r.json()


def test_trigger_publish_and_promote_creates_job(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "pp-repo1")
    cv = client.post(
        "/content-views", json={"name": "pp-cv1", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "pp-env1", "pp-path1", 0, "pp-prefix1")

    from unittest.mock import patch

    with patch("app.tasks.publish_and_promote_task.delay") as mock_delay:
        r = client.post(
            f"/content-views/{cv['id']}/publish-and-promote",
            json={"environment_id": env["id"], "description": "release candidate", "allow_unsigned": True},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "publish_and_promote"
        assert body["status"] == "pending"
        assert body["target_type"] == "environment"
        assert body["environment_id"] == env["id"]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_publish_and_promote_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = []
    repo = _create_repo(client, operator_token, "pp-repo2")
    cv = client.post(
        "/content-views", json={"name": "pp-cv2", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "pp-env2", "pp-path2", 0, "pp-prefix2")

    from unittest.mock import patch

    with patch("app.tasks.publish_and_promote_task.delay") as mock_delay:
        r = client.post(
            f"/content-views/{cv['id']}/publish-and-promote",
            json={"environment_id": env["id"]},
            headers=auth_headers(viewer_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_publish_and_promote_content_view_not_found(client, operator_token):
    r = client.post(
        "/content-views/00000000-0000-0000-0000-000000000000/publish-and-promote",
        json={"environment_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_trigger_publish_and_promote_environment_wrong_content_view_404s(client, operator_token, mock_aptly):
    """An environment already tied to content-view B (via a real promote)
    can't be targeted via content-view A's URL — same isolation pattern
    as test_set_version_description_wrong_content_view_404s. A never-
    promoted environment (content_view_id still null) is deliberately
    NOT what this test covers — that's a valid first-promote target for
    ANY content view, see test_trigger_publish_and_promote_creates_job.
    """
    mock_aptly.get_mirror_packages.return_value = []
    mock_aptly.publish_exists.return_value = False
    repo_a = _create_repo(client, operator_token, "pp-repo3a")
    repo_b = _create_repo(client, operator_token, "pp-repo3b")
    cv_a = client.post(
        "/content-views", json={"name": "pp-cv3a", "repository_ids": [repo_a["id"]]}, headers=auth_headers(operator_token)
    ).json()
    cv_b = client.post(
        "/content-views", json={"name": "pp-cv3b", "repository_ids": [repo_b["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env_b = _create_env(client, operator_token, cv_b, "pp-env3b", "pp-path3b", 0, "pp-prefix3b")
    version_b_id = client.get(f"/content-views/{cv_b['id']}/versions", headers=auth_headers(operator_token)).json()[0]["id"]
    promote_r = client.post(
        f"/lifecycle-environments/{env_b['id']}/promote",
        json={"content_view_version_id": version_b_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    r = client.post(
        f"/content-views/{cv_a['id']}/publish-and-promote",
        json={"environment_id": env_b["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_publish_and_promote_task_cuts_version_sets_description_and_promotes(client, operator_token, mock_aptly):
    """Calls publish_and_promote_task directly (real task body, not
    .delay) — same pattern used throughout tests/test_beacon.py for
    Celery tasks with no live worker in the test environment.
    """
    from unittest.mock import patch

    from app.tasks import publish_and_promote_task

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "pp-repo4")
    cv = client.post(
        "/content-views", json={"name": "pp-cv4", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "pp-env4", "pp-path4", 0, "pp-prefix4")

    with patch("app.tasks.publish_and_promote_task.delay"):
        job_r = client.post(
            f"/content-views/{cv['id']}/publish-and-promote",
            json={
                "environment_id": env["id"],
                "force": True,
                "description": "annotated at publish time",
                "allow_unsigned": True,
            },
            headers=auth_headers(operator_token),
        )
    job_id = job_r.json()["id"]

    # get_aptly_client() is called directly inside the task body (not via
    # FastAPI DI), so the client fixture's app.dependency_overrides mock
    # never applies here — same reason sync_repository_task's own direct-
    # call tests (if any existed) would need this too. Patch the factory
    # function itself so the task picks up the same mock_aptly the HTTP
    # calls above already used.
    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        publish_and_promote_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "success"

    versions = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()
    newest = versions[0]
    assert newest["description"] == "annotated at publish time"

    envs_after = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    ).json()
    env_after = next(e for e in envs_after if e["id"] == env["id"])
    assert env_after["current_version_id"] == newest["id"]
    mock_aptly.publish_snapshot.assert_called_once()


def test_publish_and_promote_task_fails_job_on_path_order_violation(client, operator_token, mock_aptly):
    """do_promote's _check_path_order raises HTTPException (409), not
    AptlyError — proves the task's except clause actually catches both,
    not just aptly failures.
    """
    from unittest.mock import patch

    from app.tasks import publish_and_promote_task

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "pp-repo5")
    cv = client.post(
        "/content-views", json={"name": "pp-cv5", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    dev = _create_env(client, operator_token, cv, "pp-dev5", "pp-path5", 0, "pp-dev5-prefix")
    staging = _create_env(client, operator_token, cv, "pp-staging5", "pp-path5", 1, "pp-staging5-prefix", prior=dev)

    # staging is position 1 in the path but dev (position 0) has never been
    # promoted to anything — staging must be rejected.
    with patch("app.tasks.publish_and_promote_task.delay"):
        job_r = client.post(
            f"/content-views/{cv['id']}/publish-and-promote",
            json={"environment_id": staging["id"], "allow_unsigned": True},
            headers=auth_headers(operator_token),
        )
    assert job_r.status_code == 201, job_r.text
    job_id = job_r.json()["id"]

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        publish_and_promote_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "failed"
    assert "dev5" in job_after.json()["log_output"] or "position" in job_after.json()["log_output"]

    # dev being untouched confirms staging's promotion never applied —
    # dev itself was never promoted either, so content_view_id is still
    # null; use promotable_for_content_view_id (matches never-promoted
    # environments too) rather than the exact-match content_view_id filter.
    envs_after = client.get(
        "/lifecycle-environments",
        params={"promotable_for_content_view_id": cv["id"]},
        headers=auth_headers(operator_token),
    ).json()
    dev_after = next(e for e in envs_after if e["id"] == dev["id"])
    assert dev_after["current_version_id"] is None
    assert dev_after["content_view_id"] is None


# ---------------------------------------------------------------------------
# POST /content-views/{id}/versions/{version_id}/delete
# ---------------------------------------------------------------------------


def test_trigger_delete_version_creates_job(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "del-repo1")
    cv = client.post(
        "/content-views", json={"name": "del-cv1", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    from unittest.mock import patch

    with patch("app.tasks.delete_content_view_version_task.delay") as mock_delay:
        r = client.post(
            f"/content-views/{cv['id']}/versions/{version['id']}/delete",
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "delete_content_view_version"
        assert body["status"] == "pending"
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_delete_version_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = []
    repo = _create_repo(client, operator_token, "del-repo2")
    cv = client.post(
        "/content-views", json={"name": "del-cv2", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    from unittest.mock import patch

    with patch("app.tasks.delete_content_view_version_task.delay") as mock_delay:
        r = client.post(
            f"/content-views/{cv['id']}/versions/{version['id']}/delete",
            headers=auth_headers(viewer_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_delete_version_content_view_not_found(client, operator_token):
    r = client.post(
        "/content-views/00000000-0000-0000-0000-000000000000/versions/00000000-0000-0000-0000-000000000000/delete",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_trigger_delete_version_not_found(client, operator_token):
    repo = _create_repo(client, operator_token, "del-repo3")
    cv = client.post(
        "/content-views", json={"name": "del-cv3", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/content-views/{cv['id']}/versions/00000000-0000-0000-0000-000000000000/delete",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_trigger_delete_version_currently_live_blocked(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "del-repo4")
    cv = client.post(
        "/content-views", json={"name": "del-cv4", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "del-env4", "del-path4", 0, "del-prefix4")
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version["id"], "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    r = client.post(
        f"/content-views/{cv['id']}/versions/{version['id']}/delete",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_trigger_delete_version_past_promoted_blocked(client, operator_token, mock_aptly):
    """A version that's no longer live (superseded by a newer one) but was
    promoted in the past — still reachable via POST /rollback — must stay
    blocked, same as the currently-live case. Deleting it would silently
    break that environment's rollback history.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "del-repo5")
    cv = client.post(
        "/content-views", json={"name": "del-cv5", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "del-env5", "del-path5", 0, "del-prefix5")
    v1 = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": v1["id"], "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    # Cut and promote v2 — v1 is no longer live, but was live in the past.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    publish_r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert publish_r.status_code == 201, publish_r.text
    v2 = publish_r.json()["content_view_version"]
    promote2_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": v2["id"]},
        headers=auth_headers(operator_token),
    )
    assert promote2_r.status_code == 200, promote2_r.text

    r = client.post(
        f"/content-views/{cv['id']}/versions/{v1['id']}/delete",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_trigger_delete_version_never_promoted_allowed(client, operator_token, mock_aptly):
    """The 409 guard is specific to promotion history — a version that was
    simply cut and never promoted anywhere is deletable, confirming the
    guard doesn't over-block unrelated versions of the same content view.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "del-repo6")
    cv = client.post(
        "/content-views", json={"name": "del-cv6", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "del-env6", "del-path6", 0, "del-prefix6")
    v1 = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]
    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": v1["id"], "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    # v2 is cut but never promoted anywhere.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    publish_r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    v2 = publish_r.json()["content_view_version"]

    from unittest.mock import patch

    with patch("app.tasks.delete_content_view_version_task.delay") as mock_delay:
        r = client.post(
            f"/content-views/{cv['id']}/versions/{v2['id']}/delete",
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        mock_delay.assert_called_once()


def test_delete_content_view_version_task_deletes_snapshots_and_row(client, operator_token, mock_aptly, db_session):
    """Calls delete_content_view_version_task directly (real task body,
    not .delay) — same pattern used for publish_and_promote_task's own
    direct-call tests. get_aptly_client() is patched for the same reason
    those needed it: called directly inside the task body, not via
    FastAPI DI, so the client fixture's dependency_overrides never applies.
    """
    from unittest.mock import patch

    from app.models import ContentViewVersion
    from app.tasks import delete_content_view_version_task

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "del-repo7")
    cv = client.post(
        "/content-views", json={"name": "del-cv7", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    with patch("app.tasks.delete_content_view_version_task.delay"):
        job_r = client.post(
            f"/content-views/{cv['id']}/versions/{version['id']}/delete",
            headers=auth_headers(operator_token),
        )
    job_id = job_r.json()["id"]

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        delete_content_view_version_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "success"

    # Real aptly delete calls happened — one per unique snapshot name.
    assert mock_aptly.delete_snapshot.call_count >= 1

    # Row actually gone.
    import uuid as _uuid

    from sqlalchemy import select as _select

    remaining = db_session.execute(
        _select(ContentViewVersion).where(ContentViewVersion.id == _uuid.UUID(version["id"]))
    ).scalar_one_or_none()
    assert remaining is None

    versions_after = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()
    assert all(v["id"] != version["id"] for v in versions_after)


def test_delete_content_view_version_task_deletes_all_snapshot_names_for_filtered_view(
    client, operator_token, mock_aptly, db_session
):
    """A content view WITH filters produces intermediate aptly snapshots
    (raw pre-filter + filter-chain steps) never referenced by `snapshots`
    — only all_snapshot_names tracks them. Confirms delete_snapshot is
    called for every one of them, not just the final snapshot name.
    """
    from unittest.mock import patch

    from app.tasks import delete_content_view_version_task

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "del-repo8")
    cv = client.post(
        "/content-views", json={"name": "del-cv8", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    filter_r = client.post(
        f"/content-views/{cv['id']}/filters",
        json={"filter_type": "include", "pattern": "nginx*"},
        headers=auth_headers(operator_token),
    )
    assert filter_r.status_code == 201, filter_r.text

    # Publish AFTER adding the filter so this cut actually goes through
    # the filtered-snapshot branch of do_publish.
    publish_r = client.post(
        f"/content-views/{cv['id']}/publish", json={"force": True}, headers=auth_headers(operator_token)
    )
    assert publish_r.status_code == 201, publish_r.text
    version = publish_r.json()["content_view_version"]
    # One repo, no components beyond "main" by default (_create_repo) ->
    # one (repo, component) entry, but the underlying cut still creates
    # TWO aptly snapshots: the raw one and the filtered one.
    assert len(version["snapshots"]) == 1

    with patch("app.tasks.delete_content_view_version_task.delay"):
        job_r = client.post(
            f"/content-views/{cv['id']}/versions/{version['id']}/delete",
            headers=auth_headers(operator_token),
        )
    job_id = job_r.json()["id"]

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        delete_content_view_version_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "success"

    # Raw snapshot + filtered snapshot = 2 delete calls, not 1 — proves
    # the intermediate (never in `snapshots`) got cleaned up too.
    assert mock_aptly.delete_snapshot.call_count == 2
    deleted_names = {call.args[0] for call in mock_aptly.delete_snapshot.call_args_list}
    assert any(name.endswith("-filtered") for name in deleted_names)
    assert any(not name.endswith("-filtered") for name in deleted_names)


def test_delete_content_view_version_task_rechecks_promotion_race(client, operator_token, mock_aptly):
    """The task re-checks the "never promoted" guard immediately before
    deleting — proves the race-window protection actually works: promote
    the version AFTER the Job was created (simulating an operator
    promoting it in the window between the trigger request and the task
    running) and confirm the task fails instead of deleting live data.
    """
    from unittest.mock import patch

    from app.tasks import delete_content_view_version_task

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "del-repo9")
    cv = client.post(
        "/content-views", json={"name": "del-cv9", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = _create_env(client, operator_token, cv, "del-env9", "del-path9", 0, "del-prefix9")
    version = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]

    with patch("app.tasks.delete_content_view_version_task.delay"):
        job_r = client.post(
            f"/content-views/{cv['id']}/versions/{version['id']}/delete",
            headers=auth_headers(operator_token),
        )
    job_id = job_r.json()["id"]

    # Promote AFTER the delete job was created but BEFORE the task runs.
    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version["id"], "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        delete_content_view_version_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "failed"
    mock_aptly.delete_snapshot.assert_not_called()

    # The version must still exist — the race guard prevented data loss.
    versions_after = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()
    assert any(v["id"] == version["id"] for v in versions_after)


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


def test_delete_content_view_referenced_by_lifecycle_environment_conflicts(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = []
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "delete-cv-repo3")
    cv = client.post(
        "/content-views",
        json={"name": "delete-cv3", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    ).json()
    version_id = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token)).json()[0]["id"]
    env_r = client.post(
        "/lifecycle-environments", json={"name": "delete-cv-env"}, headers=auth_headers(operator_token)
    )
    assert env_r.status_code == 201, env_r.text
    env = env_r.json()

    # content_view_id is only set once something's actually been promoted
    # to the environment — the delete-guard below checks an exact
    # content_view_id reference, so this must be a real promote, not just
    # a raw creation payload the old (pre-simplification) schema allowed.
    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

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
