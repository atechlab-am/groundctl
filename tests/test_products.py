import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _repo_payload(name):
    return {
        "name": name,
        "archive_url": "http://archive.ubuntu.com/ubuntu",
        "distribution": name,
        "components": ["main"],
        "architectures": ["amd64"],
    }


def test_create_product_as_operator(client, operator_token):
    r = client.post("/products", json={"name": "ubuntu-22.04", "description": "jammy family"}, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "ubuntu-22.04"
    assert body["description"] == "jammy family"
    assert body["repository_count"] == 0


def test_create_product_as_admin(client, admin_token):
    r = client.post("/products", json={"name": "ubuntu-24.04"}, headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text


def test_create_product_as_viewer_forbidden(client, viewer_token):
    r = client.post("/products", json={"name": "forbidden"}, headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_product_duplicate_name_conflicts(client, operator_token):
    r1 = client.post("/products", json={"name": "dup-product"}, headers=auth_headers(operator_token))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/products", json={"name": "dup-product"}, headers=auth_headers(operator_token))
    assert r2.status_code == 409, r2.text


def test_create_product_invalid_name_rejected(client, operator_token):
    r = client.post("/products", json={"name": "has spaces"}, headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_list_products_as_viewer(client, operator_token, viewer_token):
    client.post("/products", json={"name": "list-product"}, headers=auth_headers(operator_token))
    r = client.get("/products", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert any(p["name"] == "list-product" for p in r.json())


def test_list_products_repository_count(client, operator_token):
    product_r = client.post("/products", json={"name": "counted-product"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]
    client.post("/repositories", json=_repo_payload("counted-repo"), headers=auth_headers(operator_token))
    client.patch(
        "/repositories/counted-repo/product",
        json={"product_id": product_id},
        headers=auth_headers(operator_token),
    )

    r = client.get("/products", headers=auth_headers(operator_token))
    product = next(p for p in r.json() if p["id"] == product_id)
    assert product["repository_count"] == 1


def test_get_product_not_found(client, viewer_token):
    r = client.get("/products/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_update_product_as_operator(client, operator_token):
    product_r = client.post("/products", json={"name": "old-name"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]

    r = client.put(
        f"/products/{product_id}",
        json={"name": "new-name", "description": "updated"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "new-name"
    assert r.json()["description"] == "updated"


def test_update_product_duplicate_name_conflicts(client, operator_token):
    client.post("/products", json={"name": "taken-name"}, headers=auth_headers(operator_token))
    product_r = client.post("/products", json={"name": "renamable"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]

    r = client.put(
        f"/products/{product_id}",
        json={"name": "taken-name"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_update_product_as_viewer_forbidden(client, operator_token, viewer_token):
    product_r = client.post("/products", json={"name": "protected"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]
    r = client.put(
        f"/products/{product_id}",
        json={"name": "changed"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_delete_product_ungroups_repositories(client, operator_token):
    product_r = client.post("/products", json={"name": "deletable"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]
    client.post("/repositories", json=_repo_payload("orphan-repo"), headers=auth_headers(operator_token))
    client.patch(
        "/repositories/orphan-repo/product",
        json={"product_id": product_id},
        headers=auth_headers(operator_token),
    )

    r = client.delete(f"/products/{product_id}", headers=auth_headers(operator_token))
    assert r.status_code == 204, r.text

    repo_r = client.get("/repositories/orphan-repo", headers=auth_headers(operator_token))
    assert repo_r.json()["product_id"] is None

    get_r = client.get(f"/products/{product_id}", headers=auth_headers(operator_token))
    assert get_r.status_code == 404, get_r.text


def test_delete_product_as_viewer_forbidden(client, operator_token, viewer_token):
    product_r = client.post("/products", json={"name": "undeletable"}, headers=auth_headers(operator_token))
    product_id = product_r.json()["id"]
    r = client.delete(f"/products/{product_id}", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_delete_product_not_found(client, operator_token):
    r = client.delete("/products/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text
