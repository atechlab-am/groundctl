import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeGuard

import redis
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ansible_runner_utils import (
    AnsibleUnreachableError,
    _build_relay_inventory,
    run_playbook,
    run_playbook_against_inventory,
)
from app.aptly_client import AptlyError, get_aptly_client
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.errata_ingest import fetch_and_upsert_dsa, fetch_and_upsert_usn
from app.metrics import APTLY_DISK_USAGE_BYTES, APTLY_DISK_USAGE_PERCENT, JOBS_TOTAL
from app.models import (
    AuditAction,
    AuditLog,
    ComplianceRecord,
    ContentViewVersion,
    Job,
    JobServer,
    JobStatus,
    LifecycleEnvironment,
    Relay,
    RelaySyncStatus,
    Repository,
    Server,
    ServerFact,
    ServerLifecycleState,
    ServerStatus,
    SiteEnvironment,
)
from app.routers.compliance import ComplianceDataNotReadyError, do_check_compliance
from app.routers.repositories import do_sync_repository
from app.webhooks import send_webhook

logger = logging.getLogger("groundctl.tasks")

_redis = redis.from_url(settings.redis_url)

# Matches AptlyClient's own convention for long-running operations against a
# large fleet (see aptly_client.py's 1800s sync/publish timeouts).
_LOCK_TIMEOUT_SECONDS = 1800


def _acquire_lock(key: str):
    lock = _redis.lock(key, timeout=_LOCK_TIMEOUT_SECONDS, blocking=False)
    return lock if lock.acquire(blocking=False) else None


def _mark_job(db: Session, job: Job, status_: JobStatus, log_output: str) -> None:
    job.status = status_
    job.log_output = log_output
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    JOBS_TOTAL.labels(job_type=job.job_type.value, status=status_.value).inc()
    logger.info(
        "job %s (%s) finished: %s", job.id, job.job_type.value, status_.value,
        extra={"job_id": str(job.id), "job_type": job.job_type.value, "job_status": status_.value},
    )


def _make_progress_callback(db: Session, job: Job) -> Callable[[str], None]:
    def _on_progress(partial_log: str) -> None:
        job.log_output = partial_log
        db.commit()

    return _on_progress


def _job_server_ids(job_id: str) -> list[str]:
    db = SessionLocal()
    try:
        return [
            str(row.server_id)
            for row in db.execute(select(JobServer).where(JobServer.job_id == uuid.UUID(job_id))).scalars()
        ]
    finally:
        db.close()


def _job_servers(db: Session, job: Job) -> list[Server]:
    ids = [row.server_id for row in db.execute(select(JobServer).where(JobServer.job_id == job.id)).scalars()]
    return list(db.execute(select(Server).where(Server.id.in_(ids))).scalars())


def _update_checkin_and_reachability(db: Session, servers: list[Server], ansible_status: str) -> None:
    if ansible_status != "successful":
        return
    now = datetime.now(timezone.utc)
    for server in servers:
        server.last_seen_at = now
        if server.status == ServerStatus.unreachable:
            server.status = ServerStatus.bootstrapped
    db.commit()


def _relay_is_usable(relay: Relay | None) -> TypeGuard[Relay]:
    if relay is None or relay.sync_status != RelaySyncStatus.healthy or relay.last_sync_time is None:
        return False
    threshold = datetime.now(timezone.utc) - timedelta(hours=settings.relay_stale_threshold_hours)
    return relay.last_sync_time >= threshold


def _resolve_published_base_url(db: Session, server: Server) -> str:
    """Site-aware bootstrap URL resolution with fallback (ROADMAP Phase 5
    items 6/7). If the server has a site with a healthy, non-stale relay,
    use the relay's own published-repo URL; otherwise fall back to the
    primary's settings.published_repo_base_url. This is a real, exercised
    fallback path — not documentation-only — every bootstrap goes through it.
    """
    if server.site_id is not None:
        relay = db.execute(select(Relay).where(Relay.site_id == server.site_id)).scalar_one_or_none()
        if _relay_is_usable(relay):
            # Relay.hostname has no separate port field (see
            # docs/limitations.md) — assumes the relay's nginx is on the
            # default HTTPS port 443-equivalent for its own NGINX_PORT
            # install flag; a relay installed with a non-default
            # --nginx-port needs that reflected in hostname itself
            # (e.g. "relay.example.net:8443") until this gets a real port field.
            return f"https://{relay.hostname}"
    return settings.published_repo_base_url


def _relay_proxy_for_servers(db: Session, servers: list[Server]) -> dict[str, str]:
    """Resolves ProxyJump routing for job execution (ROADMAP Phase 5 item
    9): for each target server whose site has a healthy, non-stale relay,
    route its SSH connection through that relay. Servers with no site, or
    whose site's relay is missing/unhealthy/stale, are left direct — same
    fallback posture as _resolve_published_base_url.
    """
    site_ids = {s.site_id for s in servers if s.site_id is not None}
    if not site_ids:
        return {}
    relays_by_site = {
        r.site_id: r
        for r in db.execute(select(Relay).where(Relay.site_id.in_(site_ids))).scalars()
    }
    proxy_by_hostname: dict[str, str] = {}
    for server in servers:
        relay = relays_by_site.get(server.site_id) if server.site_id else None
        if _relay_is_usable(relay):
            proxy_by_hostname[server.hostname] = f"{relay.ssh_user}@{relay.hostname}"
    return proxy_by_hostname


def _generate_host_ssh_key(server: Server) -> tuple[str, str] | None:
    """Generates this server's own ed25519 keypair on the primary's
    filesystem (not in the database — every other secret in this codebase
    lives in files, not Postgres) if it doesn't already have one. Returns
    (key_path, pubkey_contents), or None if the server already has a key —
    existing hosts keep the shared fleet key as fallback until
    re-bootstrapped (see docs/limitations.md).

    Deliberately does NOT set Server.ssh_key_path — the caller must do that
    only AFTER the playbook run that installs this key on the host actually
    succeeds. This run's own bootstrap connection still needs the OLD key
    (shared fleet key, or a prior per-host key) since the new key hasn't
    been installed on the host yet — chicken-and-egg, same as the GPG/TLS
    trust bootstrapping above.
    """
    if server.ssh_key_path is not None:
        return None
    key_dir = os.path.join(settings.ansible_host_keys_dir, str(server.id))
    os.makedirs(key_dir, exist_ok=True)
    key_path = os.path.join(key_dir, "id_ed25519")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_path, "-q"],
        check=True,
    )
    with open(f"{key_path}.pub") as f:
        return key_path, f.read().strip()


def _tls_ca_path_if_self_signed() -> str | None:
    # No separate "is this the default self-signed cert" flag — presence at
    # the configured path is what install.sh's ensure_tls_cert() produces
    # either way, and pushing a CA-issued cert's public half to clients is
    # harmless (browsers/apt already trust it via the system store, this
    # is just redundant) so checking existence is sufficient here.
    return settings.tls_cert_path if os.path.exists(settings.tls_cert_path) else None


def _mark_servers_unreachable(db: Session, job_id: str) -> None:
    job = db.get(Job, uuid.UUID(job_id))
    if job is None:
        return
    servers = _job_servers(db, job)
    for server in servers:
        if server.status != ServerStatus.unreachable:
            server.status = ServerStatus.unreachable
            db.add(
                AuditLog(
                    user_id=None,
                    action=AuditAction.mark_server_unreachable,
                    resource_type="server",
                    resource_id=str(server.id),
                    detail={"job_id": job_id},
                )
            )
            send_webhook(
                "server.unreachable",
                {"server_id": str(server.id), "hostname": server.hostname, "job_id": job_id},
            )
    db.commit()


def _handle_task_exception(self, job_id: str) -> None:
    """Shared exception handling for _run_locked_job / _run_locked_job_multi:
      - AnsibleUnreachableError while retries remain: re-raised by the caller
        so Celery's autoretry_for retries the whole task (job stays "running"
        in the DB across retries) — this helper only handles the FINAL
        attempt's bookkeeping (detected by self.request.retries >=
        self.max_retries) and general non-retryable failures.
      - AnsibleUnreachableError on the FINAL attempt: Celery's autoretry_for
        re-raises the original exception here rather than
        MaxRetriesExceededError (verified empirically against Celery 5.6 —
        the docs suggest otherwise, but this is what actually happens) — so
        detect exhaustion via self.request.retries >= self.max_retries,
        mark the job failed, and mark every targeted server unreachable.
      - MaxRetriesExceededError: belt-and-suspenders, in case a future Celery
        version wraps the final failure differently.
    Caller is responsible for re-raising after calling this.
    """
    logger.warning("job %s gave up after repeated retries — hosts unreachable", job_id, extra={"job_id": job_id})
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is not None:
            _mark_job(db, job, JobStatus.failed, "gave up after repeated retries — hosts unreachable")
        _mark_servers_unreachable(db, job_id)
    finally:
        db.close()


def _handle_generic_exception(job_id: str, exc: Exception) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is not None:
            _mark_job(db, job, JobStatus.failed, f"groundctl job execution error: {exc}")
    finally:
        db.close()


def _get_job_or_raise(db: Session, job_id: str) -> Job:
    # job_id is always a row this same request/task chain just created and
    # committed moments earlier (see each *_task's dispatch site) — this
    # should never actually be None, but db.get() is typed Optional and a
    # dangling/deleted row is cheap to guard against explicitly rather than
    # assume away.
    job = db.get(Job, uuid.UUID(job_id))
    if job is None:
        raise ValueError(f"job {job_id} not found")
    return job


def _run_locked_job(self, job_id: str, lock_key: str, work: Callable[[Session, Job], tuple[str, str]]) -> str:
    """Shared skeleton for single-resource job tasks: opens a session, marks
    the job running, acquires the per-resource lock (fail-fast, no blocking
    wait), runs `work(db, job) -> (ansible_status, log_output)`, marks the
    final status. See _handle_task_exception for failure-mode handling.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return "job not found"

        job.celery_task_id = self.request.id
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        lock = _acquire_lock(lock_key)
        if lock is None:
            _mark_job(
                db, job, JobStatus.failed,
                "another job is already running against this resource — retry once it completes",
            )
            return "lock contention"

        try:
            ansible_status, log_output = work(db, job)
            _mark_job(
                db, job, JobStatus.success if ansible_status == "successful" else JobStatus.failed, log_output
            )
            return ansible_status
        finally:
            lock.release()
    except AnsibleUnreachableError:
        if self.request.retries >= self.max_retries:
            _handle_task_exception(self, job_id)
        raise
    except MaxRetriesExceededError:
        _handle_task_exception(self, job_id)
        raise
    except Exception as exc:  # noqa: BLE001 - must surface as a failed Job row, then re-raise for Celery
        _handle_generic_exception(job_id, exc)
        raise
    finally:
        db.close()


def _run_locked_job_multi(self, job_id: str, server_ids: list[str], work: Callable[[Session, Job], tuple[str, str]]) -> str:
    """Same contract as _run_locked_job, but acquires one Redis lock per
    target server (sorted order, to avoid cross-job deadlock between two
    jobs targeting overlapping sets in different order) instead of a single
    resource lock. Fail-fast: if any lock in the set is unavailable, every
    lock already acquired is released and the job fails immediately — no
    blocking wait, matching the single-lock skeleton's posture. This is the
    correct unit of contention for host_group/adhoc targeting because the
    thing that can actually race is the individual server, not the abstract
    group/selection (two overlapping-but-different jobs must not both run
    against a shared server just because they don't share one lock key).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return "job not found"

        job.celery_task_id = self.request.id
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        locks = []
        try:
            for server_id in sorted(server_ids):
                lock = _acquire_lock(f"groundctl:lock:server:{server_id}")
                if lock is None:
                    _mark_job(
                        db, job, JobStatus.failed,
                        "another job is already running against one or more target hosts — retry once it completes",
                    )
                    return "lock contention"
                locks.append(lock)

            ansible_status, log_output = work(db, job)
            _mark_job(
                db, job, JobStatus.success if ansible_status == "successful" else JobStatus.failed, log_output
            )
            return ansible_status
        finally:
            for lock in locks:
                lock.release()
    except AnsibleUnreachableError:
        if self.request.retries >= self.max_retries:
            _handle_task_exception(self, job_id)
        raise
    except MaxRetriesExceededError:
        _handle_task_exception(self, job_id)
        raise
    except Exception as exc:  # noqa: BLE001 - must surface as a failed Job row, then re-raise for Celery
        _handle_generic_exception(job_id, exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def bootstrap_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        server = db.get(Server, job.server_id)
        if server is None:
            raise ValueError(f"job {job.id} references a server that no longer exists")
        environment = db.get(LifecycleEnvironment, server.environment_id)
        if environment is None:
            raise ValueError(f"server {server.id}'s environment no longer exists")

        components: list[str] = ["main"]
        if environment.current_version_id is not None:
            version = db.get(ContentViewVersion, environment.current_version_id)
            if version is not None:
                seen = set()
                components = []
                for entry in version.snapshots:
                    component = entry["component"]
                    if component not in seen:
                        seen.add(component)
                        components.append(component)

        # Generated but NOT yet assigned to server.ssh_key_path — this run's
        # bootstrap connection must still use the server's existing key
        # (shared fleet key, or a prior per-host key), since the new key
        # isn't installed on the host until the playbook's authorized_key
        # task runs. Assigned only on success, below.
        new_host_key = _generate_host_ssh_key(server)

        extra_vars = {
            "published_repo_base_url": _resolve_published_base_url(db, server),
            "publish_prefix": environment.publish_prefix,
            "release": environment.release,
            "components": components,
            "environment_name": environment.name,
            "gpg_key_id": environment.gpg_key_id,
            "groundctl_tls_ca_path": _tls_ca_path_if_self_signed(),
        }
        if new_host_key is not None:
            extra_vars["groundctl_host_pubkey"] = new_host_key[1]

        ansible_status, log_output, _facts = run_playbook(
            "bootstrap_client.yml",
            [server],
            extra_vars,
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, [server]),
        )
        if ansible_status == "successful":
            server.status = ServerStatus.bootstrapped
            if new_host_key is not None:
                server.ssh_key_path = new_host_key[0]
        _update_checkin_and_reachability(db, [server], ansible_status)
        return ansible_status, log_output

    job_row = SessionLocal()
    try:
        server_id = _get_job_or_raise(job_row, job_id).server_id
    finally:
        job_row.close()
    return _run_locked_job(self, job_id, f"groundctl:lock:server:{server_id}", work)


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def apply_updates_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        servers = list(db.execute(select(Server).where(Server.environment_id == job.environment_id)).scalars())
        ansible_status, log_output, _facts = run_playbook(
            "apply_updates.yml",
            servers,
            {},
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, servers),
        )
        _update_checkin_and_reachability(db, servers, ansible_status)
        return ansible_status, log_output

    job_row = SessionLocal()
    try:
        environment_id = _get_job_or_raise(job_row, job_id).environment_id
    finally:
        job_row.close()
    return _run_locked_job(self, job_id, f"groundctl:lock:environment:{environment_id}", work)


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def gather_facts_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        servers = list(db.execute(select(Server).where(Server.environment_id == job.environment_id)).scalars())
        ansible_status, log_output, facts_by_host = run_playbook(
            "gather_facts.yml",
            servers,
            {},
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, servers),
        )

        hostname_to_server = {s.hostname: s for s in servers}
        for hostname, facts in facts_by_host.items():
            server = hostname_to_server.get(hostname)
            if server is None:
                continue
            packages_dict = facts.get("packages", {})
            installed = [
                {"name": name, "version": entry.get("version"), "arch": entry.get("arch")}
                for name, entries in packages_dict.items()
                for entry in entries
            ]
            db.add(ComplianceRecord(server_id=server.id, installed_packages=installed))

            # ansible.builtin.setup's output keys are all "ansible_"-prefixed
            # (ansible_distribution, ansible_kernel, etc.) — unlike
            # package_facts/service_facts, whose "packages"/"services" keys
            # land bare. Confirmed via live verification against a real
            # target (see docs/limitations.md's Phase 4 entry).
            mounts = facts.get("ansible_mounts", [])
            disk = [
                {
                    "mount": m.get("mount"),
                    "size_total_mb": (m.get("size_total") or 0) // (1024 * 1024),
                    "size_available_mb": (m.get("size_available") or 0) // (1024 * 1024),
                }
                for m in mounts
            ]
            services_dict = facts.get("services", {})
            services = [
                {"name": name, "state": entry.get("state"), "status": entry.get("status")}
                for name, entry in services_dict.items()
            ]
            db.add(
                ServerFact(
                    server_id=server.id,
                    os_distribution=facts.get("ansible_distribution"),
                    os_version=facts.get("ansible_distribution_version"),
                    kernel=facts.get("ansible_kernel"),
                    uptime_seconds=facts.get("ansible_uptime_seconds"),
                    disk=disk,
                    services=services,
                )
            )

        _update_checkin_and_reachability(db, servers, ansible_status)
        return ansible_status, log_output

    job_row = SessionLocal()
    try:
        environment_id = _get_job_or_raise(job_row, job_id).environment_id
    finally:
        job_row.close()
    return _run_locked_job(self, job_id, f"groundctl:lock:environment:{environment_id}", work)


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def bulk_apply_updates_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        servers = _job_servers(db, job)
        ansible_status, log_output, _facts = run_playbook(
            "apply_updates.yml",
            servers,
            {},
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, servers),
        )
        _update_checkin_and_reachability(db, servers, ansible_status)
        return ansible_status, log_output

    server_ids = _job_server_ids(job_id)
    return _run_locked_job_multi(self, job_id, server_ids, work)


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def run_command_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        servers = _job_servers(db, job)
        audit = db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == str(job.id), AuditLog.action == AuditAction.trigger_run_command
            )
        ).scalar_one()
        if audit.detail is None:
            raise ValueError(f"audit log for job {job.id} is missing its command detail")
        command = audit.detail["command"]
        ansible_status, log_output, _facts = run_playbook(
            "run_command.yml",
            servers,
            {"groundctl_command": command},
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, servers),
        )
        _update_checkin_and_reachability(db, servers, ansible_status)
        return ansible_status, log_output

    server_ids = _job_server_ids(job_id)
    return _run_locked_job_multi(self, job_id, server_ids, work)


@celery_app.task(bind=True, autoretry_for=(AnsibleUnreachableError,), retry_backoff=True, max_retries=3)
def manage_package_task(self, job_id: str) -> str:
    def work(db: Session, job: Job) -> tuple[str, str]:
        server = db.get(Server, job.server_id)
        if server is None:
            raise ValueError(f"job {job.id} references a server that no longer exists")
        audit = db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == str(job.id), AuditLog.action == AuditAction.trigger_manage_package
            )
        ).scalar_one()
        if audit.detail is None:
            raise ValueError(f"audit log for job {job.id} is missing its package detail")
        package_name = audit.detail["package_name"]
        package_state = "present" if audit.detail["action"] == "install" else "absent"
        ansible_status, log_output, _facts = run_playbook(
            "manage_package.yml",
            [server],
            {"groundctl_package_name": package_name, "groundctl_package_state": package_state},
            on_progress=_make_progress_callback(db, job),
            ssh_proxy_by_hostname=_relay_proxy_for_servers(db, [server]),
        )
        _update_checkin_and_reachability(db, [server], ansible_status)
        return ansible_status, log_output

    job_row = SessionLocal()
    try:
        server_id = _get_job_or_raise(job_row, job_id).server_id
    finally:
        job_row.close()
    return _run_locked_job(self, job_id, f"groundctl:lock:server:{server_id}", work)


@celery_app.task(bind=True)
def sync_repository_task(self, job_id: str) -> str:
    """Backs the operator-triggered POST /repositories/{name}/sync endpoint
    (app/routers/repositories.py) — runs the same do_sync_repository the
    nightly scheduled_sync_all_repositories below uses, but as a tracked Job
    so the UI can show live status and the operator can click through to it,
    instead of the old inline blocking call. Locked per-repository (not
    _run_locked_job — that helper's `work` contract expects an ansible
    (status, log_output) tuple; a mirror sync is a single aptly call with no
    ansible run involved).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return "job not found"

        job.celery_task_id = self.request.id
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        repository = db.get(Repository, job.repository_id)
        if repository is None:
            _mark_job(db, job, JobStatus.failed, f"repository {job.repository_id} no longer exists")
            return "repository not found"

        lock = _acquire_lock(f"groundctl:lock:repository:{repository.id}")
        if lock is None:
            _mark_job(
                db, job, JobStatus.failed,
                "another sync is already running against this repository — retry once it completes",
            )
            return "lock contention"

        aptly = get_aptly_client()
        try:
            do_sync_repository(repository, db, aptly, user_id=job.created_by_user_id)
            repository.size_bytes = aptly.get_mirror_size_bytes(repository.name)
            db.commit()
            _mark_job(db, job, JobStatus.success, f"synced {repository.name}")
            return "successful"
        except AptlyError as exc:
            db.rollback()
            job = _get_job_or_raise(db, job_id)
            _mark_job(db, job, JobStatus.failed, str(exc))
            return "failed"
        finally:
            lock.release()
    finally:
        db.close()


@celery_app.task
def scheduled_sync_all_repositories() -> str:
    db = SessionLocal()
    aptly = get_aptly_client()
    try:
        repositories = list(db.execute(select(Repository)).scalars())
        errors = []
        for repository in repositories:
            try:
                do_sync_repository(repository, db, aptly, user_id=None)
                repository.size_bytes = aptly.get_mirror_size_bytes(repository.name)
                db.commit()
            except AptlyError as exc:
                db.rollback()
                errors.append(f"{repository.name}: {exc}")
        return f"synced {len(repositories) - len(errors)}/{len(repositories)} repositories" + (
            f"; errors: {errors}" if errors else ""
        )
    finally:
        db.close()


@celery_app.task
def scheduled_compliance_scan() -> str:
    db = SessionLocal()
    aptly = get_aptly_client()
    try:
        servers = list(db.execute(select(Server)).scalars())
        checked = 0
        skipped = 0
        for server in servers:
            try:
                do_check_compliance(server, db, aptly)
                db.commit()
                checked += 1
            except (ComplianceDataNotReadyError, AptlyError):
                db.rollback()
                skipped += 1
        return f"checked {checked} servers, skipped {skipped} (no facts yet or unpublished environment)"
    finally:
        db.close()


@celery_app.task
def ingest_usn_errata() -> str:
    db = SessionLocal()
    try:
        upserted, skipped = fetch_and_upsert_usn(db)
        db.commit()
        return f"upserted {upserted} USN errata, skipped {skipped} malformed entries"
    finally:
        db.close()


@celery_app.task
def ingest_dsa_errata() -> str:
    db = SessionLocal()
    try:
        upserted, skipped = fetch_and_upsert_dsa(db)
        db.commit()
        return f"upserted {upserted} DSA errata, skipped {skipped} malformed entries"
    finally:
        db.close()


@celery_app.task
def scheduled_flag_stale_servers() -> str:
    """Daily staleness sweep — see docs/limitations.md. last_seen_at is only
    updated by successful groundctl-triggered jobs/self-registration, not a
    heartbeat, so this flags hosts groundctl simply hasn't run anything
    against recently, not necessarily hosts that are actually down.
    """
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(hours=settings.stale_checkin_hours)
        stale = list(
            db.execute(
                select(Server).where(
                    Server.lifecycle_state == ServerLifecycleState.active,
                    (Server.last_seen_at.is_(None)) | (Server.last_seen_at < threshold),
                )
            ).scalars()
        )
        for server in stale:
            db.add(
                AuditLog(
                    user_id=None,
                    action=AuditAction.flag_stale_server,
                    resource_type="server",
                    resource_id=str(server.id),
                    detail={"last_seen_at": server.last_seen_at.isoformat() if server.last_seen_at else None},
                )
            )
            send_webhook(
                "server.stale",
                {
                    "server_id": str(server.id),
                    "hostname": server.hostname,
                    "last_seen_at": server.last_seen_at.isoformat() if server.last_seen_at else None,
                },
            )
        db.commit()
        return f"flagged {len(stale)} stale servers (threshold {settings.stale_checkin_hours}h)"
    finally:
        db.close()


@celery_app.task
def scheduled_sync_relays() -> str:
    """Primary-initiated rsync-over-SSH sync to every Relay, scheduled via
    Celery Beat rather than triggered inline by promote/rollback — keeps
    promotion fast and decoupled (aptly's own publish call can already take
    up to 1800s) and means a relay being down never blocks or fails a
    primary promotion. Not tracked as a Job row, matching every other
    scheduled task (fire-and-forget, per-item try/except, summary string).
    See docs/relays.md for the sync model and docs/limitations.md for the
    eventual-consistency caveat (a promoted environment reaches its relays
    on the next run of this task, not immediately).
    """
    db = SessionLocal()
    try:
        relays = list(db.execute(select(Relay)).scalars())
        synced = 0
        errors: list[str] = []
        for relay in relays:
            prefixes = [
                env.publish_prefix
                for env in db.execute(
                    select(LifecycleEnvironment)
                    .join(SiteEnvironment, SiteEnvironment.environment_id == LifecycleEnvironment.id)
                    .where(SiteEnvironment.site_id == relay.site_id)
                ).scalars()
            ]
            if not prefixes:
                continue
            try:
                ansible_status, _log, facts_by_host = run_playbook_against_inventory(
                    "sync_relay.yml", _build_relay_inventory(relay), {"groundctl_prefixes": prefixes}
                )
                if ansible_status != "successful":
                    raise AptlyError(f"sync_relay.yml reported status={ansible_status}")

                content_size = None
                host_facts = facts_by_host.get(relay.hostname, {})
                size_str = host_facts.get("groundctl_content_size_bytes")
                if size_str is not None:
                    content_size = int(size_str)

                relay.sync_status = RelaySyncStatus.healthy
                relay.last_sync_time = datetime.now(timezone.utc)
                if content_size is not None:
                    relay.content_size_bytes = content_size
                db.commit()
                synced += 1
            except Exception as exc:  # noqa: BLE001 - per-relay isolation, must not abort the batch
                db.rollback()
                relay.sync_status = RelaySyncStatus.failed
                db.commit()
                errors.append(f"{relay.hostname}: {exc}")
                logger.warning(
                    "relay sync failed for %s: %s", relay.hostname, exc, extra={"relay_id": str(relay.id)}
                )
                send_webhook(
                    "relay.sync_failed",
                    {"relay_id": str(relay.id), "hostname": relay.hostname, "error": str(exc)},
                )
        return f"synced {synced}/{len(relays)} relays" + (f"; errors: {errors}" if errors else "")
    finally:
        db.close()


@celery_app.task
def scheduled_flag_stale_relays() -> str:
    """Daily relay staleness sweep, mirrors scheduled_flag_stale_servers.
    A relay whose last_sync_time exceeds relay_stale_threshold_hours is
    flagged stale — bootstrap/job-routing fallback to the primary then
    kicks in automatically (see _resolve_published_base_url /
    _relay_proxy_for_servers), so this is about visibility, not the
    fallback mechanism itself (which doesn't depend on this task running).
    """
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(hours=settings.relay_stale_threshold_hours)
        stale = list(
            db.execute(
                select(Relay).where(
                    Relay.sync_status != RelaySyncStatus.stale,
                    (Relay.last_sync_time.is_(None)) | (Relay.last_sync_time < threshold),
                )
            ).scalars()
        )
        for relay in stale:
            relay.sync_status = RelaySyncStatus.stale
            send_webhook(
                "relay.stale",
                {
                    "relay_id": str(relay.id),
                    "hostname": relay.hostname,
                    "last_sync_time": relay.last_sync_time.isoformat() if relay.last_sync_time else None,
                },
            )
        db.commit()
        return f"flagged {len(stale)} stale relays (threshold {settings.relay_stale_threshold_hours}h)"
    finally:
        db.close()


@celery_app.task
def scheduled_purge_audit_logs() -> str:
    """Daily retention sweep. Deletes AuditLog rows older than
    audit_log_retention_days outright — no special-casing for rows needed
    to reconstruct very old promotion history (Phase 1's
    switch_publish/rollback_environment audit trail). That's a real but
    narrow edge case (reconstructing promotion history older than the
    retention window) documented in docs/limitations.md rather than
    justifying extra complexity here.
    """
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)
        result = db.execute(delete(AuditLog).where(AuditLog.created_at < threshold))
        db.commit()
        # Session.execute()'s return type is the generic Result[Any] in
        # SQLAlchemy's stubs; .rowcount is real on the CursorResult a DELETE
        # actually returns at runtime, mypy just can't see that from here.
        rowcount = result.rowcount  # type: ignore[attr-defined]
        return f"purged {rowcount} audit log rows older than {settings.audit_log_retention_days}d"
    finally:
        db.close()


# Path aptly writes its data pool + published tree to (scripts/lib/aptly.sh's
# ensure_aptly_user_and_dirs). Disk usage is checked on this mount, not the
# whole filesystem — matches what actually grows unbounded.
APTLY_DATA_ROOT = "/var/lib/groundctl/aptly"


@celery_app.task
def scheduled_aptly_maintenance() -> str:
    """Weekly: runs aptly's own db cleanup (removes package files no longer
    referenced by any mirror/snapshot — the pool otherwise grows unbounded,
    see docs/limitations.md) and checks disk usage on the aptly data root,
    firing a disk.usage_high webhook and updating the Prometheus gauges if
    usage crosses disk_usage_warn_percent. cleanup_db failure doesn't skip
    the disk check (they're independent concerns) but does get reported.
    """
    cleanup_result = "skipped"
    try:
        aptly = get_aptly_client()
        aptly.cleanup_db()
        cleanup_result = "ok"
    except AptlyError as exc:
        cleanup_result = f"failed: {exc}"
        logger.warning("aptly db cleanup failed: %s", exc)

    try:
        usage = shutil.disk_usage(APTLY_DATA_ROOT)
        percent_used = (usage.used / usage.total) * 100 if usage.total else 0.0
        APTLY_DISK_USAGE_BYTES.set(usage.used)
        APTLY_DISK_USAGE_PERCENT.set(percent_used)
        if percent_used >= settings.disk_usage_warn_percent:
            logger.warning("aptly disk usage at %.1f%% (threshold %.1f%%)", percent_used, settings.disk_usage_warn_percent)
            send_webhook(
                "disk.usage_high",
                {
                    "path": APTLY_DATA_ROOT,
                    "used_bytes": usage.used,
                    "total_bytes": usage.total,
                    "percent_used": round(percent_used, 1),
                    "threshold_percent": settings.disk_usage_warn_percent,
                },
            )
        disk_result = f"{percent_used:.1f}% used"
    except OSError as exc:
        disk_result = f"disk check failed: {exc}"
        logger.warning("aptly disk usage check failed: %s", exc)

    return f"cleanup: {cleanup_result}; disk: {disk_result}"
