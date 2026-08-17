import stat
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
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


def _create_cv(client, operator_token, repo, name="cv"):
    r = client.post(
        "/content-views",
        json={"name": name, "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_env(client, operator_token, cv, name="dev", path_name="main", position=0, publish_prefix="dev"):
    # An environment is now pure path structure with NO content view of its
    # own (LifecycleEnvironmentCreate takes only name/description/
    # prior_environment_id) — `cv` is accepted for call-site compatibility
    # but intentionally left UNASSIGNED here. Enrollment only needs
    # env["id"] to exist to hang an activation key/server off of — no test
    # in this file (including the end-to-end script test) reads environment
    # content-view state, so skipping the assign+promote step keeps this
    # helper cheap. path_name/position/publish_prefix args kept for
    # call-site compatibility only.
    r = client.post(
        "/lifecycle-environments", json={"name": name}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


def _make_env(client, operator_token, suffix):
    repo = _create_repo(client, operator_token, f"en-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"en-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"en-env-{suffix}", f"en-path-{suffix}", 0, f"en-prefix-{suffix}")


def _create_activation_key(client, operator_token, env, name="ek", **overrides):
    payload = {"name": name, "environment_id": env["id"]}
    payload.update(overrides)
    r = client.post("/activation-keys", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    return r.json()


def _register_payload(token, hostname="host1.example.com", ip="10.0.0.1", ssh_user="ubuntu"):
    return {"token": token, "hostname": hostname, "ip_address": ip, "ssh_user": ssh_user}


def test_register_with_valid_token_creates_server(client, operator_token):
    env = _make_env(client, operator_token, "1")
    key = _create_activation_key(client, operator_token, env, "reg-key1")

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-a.example.com"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hostname"] == "host-a.example.com"
    assert body["environment_id"] == env["id"]
    assert "server_id" in body

    # Verify the server row was actually created and use_count incremented.
    get_key = client.get(f"/activation-keys/{key['id']}", headers=auth_headers(operator_token))
    assert get_key.json()["use_count"] == 1


def test_register_no_auth_header_required(client, operator_token):
    env = _make_env(client, operator_token, "noauth")
    key = _create_activation_key(client, operator_token, env, "reg-key-noauth")

    # Deliberately no Authorization header — this is the point of the endpoint.
    r = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-noauth.example.com"),
    )
    assert r.status_code == 201, r.text


def test_register_with_invalid_token_401(client):
    r = client.post("/enrollment/register", json=_register_payload("not-a-real-token", "host-bad.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_revoked_token_401(client, operator_token):
    env = _make_env(client, operator_token, "2")
    key = _create_activation_key(client, operator_token, env, "reg-key2")
    revoke = client.post(f"/activation-keys/{key['id']}/revoke", headers=auth_headers(operator_token))
    assert revoke.status_code == 200, revoke.text

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-revoked.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_expired_token_401(client, operator_token, db_session):
    from app.models import ActivationKey

    env = _make_env(client, operator_token, "3")
    key = _create_activation_key(client, operator_token, env, "reg-key3")

    # API doesn't allow creating with a past expires_at directly via schema
    # validation concerns, so seed it via the DB directly per task instructions.
    db_key = db_session.get(ActivationKey, key["id"])
    db_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-expired.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_exhausted_max_uses_401(client, operator_token):
    env = _make_env(client, operator_token, "4")
    key = _create_activation_key(client, operator_token, env, "reg-key4", max_uses=1)

    r1 = client.post("/enrollment/register", json=_register_payload(key["token"], "host-first.example.com"))
    assert r1.status_code == 201, r1.text

    r2 = client.post("/enrollment/register", json=_register_payload(key["token"], "host-second.example.com"))
    assert r2.status_code == 401, r2.text


def test_register_idempotent_same_hostname_updates_existing_server(client, operator_token):
    env = _make_env(client, operator_token, "5")
    key = _create_activation_key(client, operator_token, env, "reg-key5")

    r1 = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-idempotent.example.com", ip="10.0.0.5"),
    )
    assert r1.status_code == 201, r1.text
    server_id_1 = r1.json()["server_id"]

    # Router logic (enrollment.py): looks up Server by hostname; if found,
    # updates ip_address/ssh_user/last_seen_at on the SAME row rather than
    # creating a new one or erroring. environment_id is left untouched.
    r2 = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-idempotent.example.com", ip="10.0.0.6"),
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["server_id"] == server_id_1
    assert r2.json()["environment_id"] == env["id"]


def test_get_ssh_public_key_no_auth_required(client, tmp_path, monkeypatch):
    key_path = tmp_path / "id_ed25519"
    key_path.with_suffix(".pub").write_text("ssh-ed25519 AAAAtest fleet-key\n")
    monkeypatch.setattr(settings, "ansible_private_key_path", str(key_path))

    r = client.get("/enrollment/ssh-public-key")
    assert r.status_code == 200, r.text
    assert r.text == "ssh-ed25519 AAAAtest fleet-key\n"
    assert r.headers["content-type"].startswith("text/plain")


def test_get_ssh_public_key_missing_returns_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ansible_private_key_path", str(tmp_path / "does-not-exist"))

    r = client.get("/enrollment/ssh-public-key")
    assert r.status_code == 503, r.text


def test_get_enrollment_script_no_auth_required(client, operator_token):
    env = _make_env(client, operator_token, "script1")
    key = _create_activation_key(client, operator_token, env, "script-key1")

    r = client.get("/enrollment/script", params={"token": key["token"]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/x-shellscript")
    assert key["token"] in r.text
    assert "/enrollment/register" in r.text
    assert "/enrollment/ssh-public-key" in r.text
    assert "authorized_keys" in r.text


def test_get_enrollment_script_is_valid_bash(client, operator_token):
    env = _make_env(client, operator_token, "script2")
    key = _create_activation_key(client, operator_token, env, "script-key2")

    r = client.get("/enrollment/script", params={"token": key["token"]})
    assert r.status_code == 200, r.text

    result = subprocess.run(["bash", "-n"], input=r.text, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_get_enrollment_script_quotes_token_defensively(client, operator_token):
    # secrets.token_urlsafe never produces shell metacharacters, but the
    # endpoint takes the token as a raw query param — confirm a
    # maximally hostile value still round-trips through shlex.quote
    # without breaking the script's syntax (same discipline as the
    # sys.argv-based admin-password handling in scripts/lib/app.sh).
    hostile_token = "a'; rm -rf /; echo '"

    r = client.get("/enrollment/script", params={"token": hostile_token})
    assert r.status_code == 200, r.text

    result = subprocess.run(["bash", "-n"], input=r.text, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "rm -rf /" not in result.stderr


def test_enrollment_script_end_to_end(tmp_path, db_session, mock_aptly, monkeypatch):
    """Actually runs the generated script (with `curl` replaced by a stub
    that calls back into a live TestClient-backed HTTP server) against a
    fresh fake root, confirming it registers the host AND installs the
    fleet pubkey into authorized_keys — the real thing this endpoint
    exists for, not just that it renders parseable bash.
    """
    import threading

    import uvicorn

    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    key_path = tmp_path / "id_ed25519"
    key_path.with_suffix(".pub").write_text("ssh-ed25519 AAAAendtoend fleet-key\n")
    monkeypatch.setattr(settings, "ansible_private_key_path", str(key_path))

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            pass
        port = server.servers[0].sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        with TestClient(app) as setup_client:
            token = _token_for(setup_client, db_session, Role.operator)
            env = _make_env(setup_client, token, "e2e")
            key = _create_activation_key(setup_client, token, env, "e2e-key")

            script_resp = setup_client.get("/enrollment/script", params={"token": key["token"]})
            assert script_resp.status_code == 200, script_resp.text
            script_text = script_resp.text.replace(settings.groundctl_api_base_url, base_url)

        fake_root = tmp_path / "fake-root"
        (fake_root / ".ssh").mkdir(parents=True)
        script_path = tmp_path / "enroll.sh"

        # Two harness-only substitutions, script itself ships unchanged:
        # (1) drop the EUID==0 guard — EUID is a read-only bash builtin,
        # there's no way to fake root for it short of actually running as
        # root (not assumed available here); the guard is a one-line,
        # self-evidently-correct check, what's worth verifying live is
        # everything past it. (2) override ip_address instead of relying
        # on `hostname -I`, which is GNU/Linux-only (the script's real
        # target is Ubuntu/Debian) and doesn't exist on this dev machine's
        # BSD/macOS hostname.
        script_text_local = (
            script_text.replace("/root/.ssh", str(fake_root / ".ssh"))
            .replace(
                'if [[ "${EUID}" -ne 0 ]]; then\n    echo "[groundctl-register] must be run as root (try: sudo bash)" >&2\n    exit 1\nfi\n',
                "",
            )
            .replace(
                'ip_address="$(hostname -I 2>/dev/null | awk \'{print $1}\')"',
                'ip_address="127.0.0.1"',
            )
        )
        assert "must be run as root" not in script_text_local, "root-check removal pattern didn't match"
        assert "hostname -I" not in script_text_local, "ip_address override pattern didn't match"
        script_path.write_text(script_text_local)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

        authorized_keys = (fake_root / ".ssh" / "authorized_keys").read_text()
        assert "ssh-ed25519 AAAAendtoend fleet-key" in authorized_keys

        with TestClient(app) as verify_client:
            verify_token = _token_for(verify_client, db_session, Role.viewer)
            servers = verify_client.get("/servers", headers=auth_headers(verify_token)).json()
            assert any(s["hostname"] for s in servers)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        app.dependency_overrides.clear()
