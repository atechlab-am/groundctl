def test_health_ok_when_all_dependencies_reachable(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


def test_health_returns_503_when_aptly_unreachable(db_session, mock_aptly_unreachable):
    from tests.conftest import TestClient

    from app.aptly_client import get_aptly_client
    from app.main import app

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 503, r.text
            body = r.json()
            assert body["status"] == "degraded"
            assert body["checks"]["aptly"].startswith("error:")
            assert body["checks"]["database"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_metrics_exposes_prometheus_format(client):
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    assert "groundctl_http_requests_total" in r.text
