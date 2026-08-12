import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class ServerStatus(str, enum.Enum):
    registered = "registered"
    bootstrapped = "bootstrapped"
    unreachable = "unreachable"


class ServerLifecycleState(str, enum.Enum):
    # Distinct from ServerStatus (reachability/bootstrap state): this is the
    # human-facing lifecycle. Kept separate so "decommissioned" doesn't fight
    # with "unreachable" — a decommissioned host is *expected* unreachable.
    active = "active"
    decommissioned = "decommissioned"


class JobType(str, enum.Enum):
    bootstrap = "bootstrap"
    apply_updates = "apply_updates"
    gather_facts = "gather_facts"
    bulk_apply_updates = "bulk_apply_updates"
    run_command = "run_command"
    manage_package = "manage_package"
    sync_repository = "sync_repository"


class JobTargetType(str, enum.Enum):
    server = "server"
    environment = "environment"
    host_group = "host_group"
    adhoc = "adhoc"
    repository = "repository"


class PackageAction(str, enum.Enum):
    install = "install"
    remove = "remove"


class RelaySyncStatus(str, enum.Enum):
    never_synced = "never_synced"
    healthy = "healthy"
    stale = "stale"
    failed = "failed"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class FilterType(str, enum.Enum):
    include = "include"
    exclude = "exclude"
    # pattern holds an ISO date string for this type — "include only security
    # fixes published on/after this date," resolved against Erratum/
    # ErratumPackage rather than a raw package-name pattern.
    errata_since = "errata_since"


class ErratumSource(str, enum.Enum):
    usn = "usn"
    dsa = "dsa"


class AuditAction(str, enum.Enum):
    create_user = "create_user"
    create_repository = "create_repository"
    sync_repository = "sync_repository"
    update_repository = "update_repository"
    delete_repository = "delete_repository"
    cut_snapshot = "cut_snapshot"
    publish_content_view = "publish_content_view"
    switch_publish = "switch_publish"
    rollback_environment = "rollback_environment"
    create_content_view = "create_content_view"
    create_content_view_filter = "create_content_view_filter"
    create_lifecycle_environment = "create_lifecycle_environment"
    create_server = "create_server"
    trigger_bootstrap = "trigger_bootstrap"
    trigger_apply_updates = "trigger_apply_updates"
    trigger_gather_facts = "trigger_gather_facts"
    create_host_group = "create_host_group"
    update_host_group_membership = "update_host_group_membership"
    create_activation_key = "create_activation_key"
    revoke_activation_key = "revoke_activation_key"
    register_via_activation_key = "register_via_activation_key"
    trigger_bulk_apply_updates = "trigger_bulk_apply_updates"
    trigger_run_command = "trigger_run_command"
    trigger_manage_package = "trigger_manage_package"
    decommission_server = "decommission_server"
    mark_server_unreachable = "mark_server_unreachable"
    flag_stale_server = "flag_stale_server"
    create_site = "create_site"
    update_site = "update_site"
    create_relay = "create_relay"
    update_site_environments = "update_site_environments"
    assign_server_site = "assign_server_site"
    login = "login"
    login_failed = "login_failed"
    export_audit_log = "export_audit_log"
    update_user = "update_user"
    deactivate_user = "deactivate_user"
    reactivate_user = "reactivate_user"
    change_own_password = "change_own_password"
    update_branding = "update_branding"
    update_instance_settings = "update_instance_settings"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), nullable=False, default=Role.viewer)
    # Deactivation, not deletion — matches Server's decommission /
    # ActivationKey's revoked posture elsewhere in this app: the row (and
    # everything it's a foreign key target for — AuditLog.user_id,
    # ActivationKey.created_by_user_id, etc.) stays intact. A deactivated
    # user can no longer log in (checked at /auth/login and /auth/ui-login)
    # but their historical actions remain attributable.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RefreshToken(Base):
    """DB-backed, revocable — not a stateless rotating JWT. Same
    hash-only-storage posture as ActivationKey: the raw token is returned
    once at login/refresh and never again. Rotated on every use of
    POST /auth/refresh (old row revoked, new row issued) to limit replay
    window if a refresh token is ever disclosed.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    archive_url: Mapped[str] = mapped_column(String, nullable=False)
    distribution: Mapped[str] = mapped_column(String, nullable=False)
    components: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    architectures: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Sum of Size across every package aptly reports for this mirror as of
    # last_synced_at — populated after a successful sync_repository job
    # (app/tasks.py's sync_repository_task), null until the first sync
    # completes. Not maintained incrementally; each sync recomputes it fresh
    # from GET /api/mirrors/{name}/packages so it can never drift from what
    # aptly actually holds.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_sync_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class InstanceSetting(Base):
    """Runtime-editable operational tunables — single shared row, same
    fixed-id singleton pattern as Branding above. Every column is nullable:
    NULL means "not overridden, use the config.py/env-var default" (see
    app/instance_settings.py's get_effective_settings, the only place these
    columns and their config.py fallbacks are resolved together). Only
    tunables that are safe to change without a restart and carry no secret/
    connection-string shape belong here — database_url, jwt_secret,
    aptly_api_url, TLS/SSH key paths etc. stay env-only by design (see
    CLAUDE.md's Secrets section); webhook_secret is the one exception,
    included because rotating it is a legitimate runtime admin operation,
    handled write-only (see BrandingRead-style read schema in schemas.py —
    InstanceSettingsRead never echoes it back).
    """

    __tablename__ = "instance_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_log_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activation_key_default_ttl_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stale_checkin_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relay_stale_threshold_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_usage_warn_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class VersionCheck(Base):
    """Cached result of the daily GitHub-releases check (scheduled_check_
    for_new_version, app/tasks.py) — single shared row, same fixed-id
    singleton pattern as Branding/InstanceSetting. Exists so GET /version
    (polled by every logged-in browser tab) never itself calls GitHub —
    only the scheduled task does, once a day, avoiding both per-user rate
    limiting and making the endpoint fast/available even if GitHub is
    unreachable at request time (stale cached data beats no data).
    """

    __tablename__ = "version_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    latest_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Null means the last check attempt failed (network error, rate limit,
    # unexpected response shape) — GET /version falls back to "no update
    # info available" rather than showing stale-but-wrong data indefinitely
    # only when this has never once succeeded; a prior successful value is
    # preserved across a single failed re-check (see the task's docstring).
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ContentView(Base):
    __tablename__ = "content_views"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", secondary="content_view_repositories"
    )
    filters: Mapped[list["ContentViewFilter"]] = relationship("ContentViewFilter")


class ContentViewRepository(Base):
    __tablename__ = "content_view_repositories"

    content_view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_views.id"), primary_key=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id"), primary_key=True
    )


class ContentViewFilter(Base):
    __tablename__ = "content_view_filters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_views.id"), nullable=False
    )
    filter_type: Mapped[FilterType] = mapped_column(Enum(FilterType, name="filter_type"), nullable=False)
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ContentViewVersion(Base):
    __tablename__ = "content_view_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_views.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # One entry per (repository, component) pair included in this version:
    # [{"repository_id": str, "repository_name": str, "snapshot_name": str,
    #   "component": str}, ...]
    # Immutable once written — this IS the immutable content-view-version
    # invariant; never updated after insert.
    snapshots: Mapped[list] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (UniqueConstraint("content_view_id", "version"),)


class LifecycleEnvironment(Base):
    __tablename__ = "lifecycle_environments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Ordered-path model: environments sharing path_name form one ordered
    # chain by position (0-based). Promotion into position N requires the
    # target version to already be current at position N-1 in the same path.
    path_name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content_view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_views.id"), nullable=False
    )
    distro: Mapped[str] = mapped_column(String, nullable=False)
    release: Mapped[str] = mapped_column(String, nullable=False)
    publish_prefix: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_view_versions.id"), nullable=True
    )
    # Nullable — unsigned publishing stays available as an explicit choice
    # (LifecycleEnvironmentCreate.allow_unsigned), but new environments
    # require this to be set unless that flag is passed. See docs/gpg-signing.md.
    gpg_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (UniqueConstraint("path_name", "position"),)


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname: Mapped[str] = mapped_column(String, nullable=False)
    ip_address: Mapped[str] = mapped_column(String, nullable=False)
    ssh_user: Mapped[str] = mapped_column(String, nullable=False)
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lifecycle_environments.id"), nullable=False
    )
    status: Mapped[ServerStatus] = mapped_column(
        Enum(ServerStatus, name="server_status"), nullable=False, default=ServerStatus.registered
    )
    lifecycle_state: Mapped[ServerLifecycleState] = mapped_column(
        Enum(ServerLifecycleState, name="server_lifecycle_state"),
        nullable=False,
        default=ServerLifecycleState.active,
    )
    # Set by any job that completes successfully against this server (see
    # tasks.py's _update_checkin_and_reachability) or by self-registration.
    # Not a heartbeat — only updated by groundctl-triggered activity.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL means this Server was created via the human-authenticated
    # POST /servers. Set means it self-registered via an activation key —
    # the audit trail for "how did this host get here."
    registered_via_activation_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activation_keys.id"), nullable=True
    )
    # Nullable — most servers may have no site/relay and are served directly
    # by the primary. When set, bootstrap and job-execution routing resolve
    # this server's site's Relay (see tasks.py's _resolve_published_base_url
    # / _relay_proxy_for_servers), falling back to the primary if the relay
    # is missing, unhealthy, or stale.
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True)
    # Nullable — falls back to the shared fleet key (settings.ansible_private_key_path)
    # when unset, e.g. hosts bootstrapped before per-host keys existed. Set by
    # bootstrap_task.work() the first time a host is bootstrapped after this
    # feature landed. Path only — the key itself lives on the primary's
    # filesystem under /etc/groundctl/ansible-keys/hosts/<server_id>/, never
    # in the database. See docs/limitations.md for the shared-key fallback.
    ssh_key_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    environment: Mapped["LifecycleEnvironment"] = relationship("LifecycleEnvironment")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, name="job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.pending
    )
    # Records targeting *intent* (server / environment / host_group / adhoc).
    # The resolved set of servers this job actually ran against is recorded
    # separately in JobServer, independent of later group-membership changes.
    target_type: Mapped[JobTargetType] = mapped_column(
        Enum(JobTargetType, name="job_target_type"), nullable=False, default=JobTargetType.server
    )
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id"), nullable=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lifecycle_environments.id"), nullable=True
    )
    host_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("host_groups.id"), nullable=True
    )
    # SET NULL (unlike the other target FKs above, which have no delete path
    # to worry about — servers/environments/host_groups are never hard
    # deleted): repositories now can be (delete_repository below), and a
    # past sync job's history should survive that, not get blocked by or
    # cascade into deleting it.
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    log_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Correlates this row with its Celery task for cancellation (control.revoke)
    # and the stuck-job reaper (control.inspect().active()). Internal — never
    # exposed via JobRead.
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction, name="audit_action"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ComplianceRecord(Base):
    __tablename__ = "compliance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=False)
    installed_packages: Mapped[list] = mapped_column(JSON, nullable=False)
    gathered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ComplianceCheckLog(Base):
    """Persisted result of a drift check — distinct from ComplianceRecord,
    which stores raw installed-package facts. Written by both the on-demand
    POST /compliance/servers/{id}/check endpoint and the weekly scheduled
    scan, so history accumulates from either trigger path.
    """

    __tablename__ = "compliance_check_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=False)
    drift: Mapped[list] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Erratum(Base):
    """One row per USN/DSA advisory. Mutable-upstream by design (unlike
    ContentViewVersion) — advisories are occasionally revised after first
    publication; re-ingestion upserts by advisory_id rather than treating
    existing rows as immutable.
    """

    __tablename__ = "errata"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    advisory_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[ErratumSource] = mapped_column(Enum(ErratumSource, name="erratum_source"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    cves: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    # Neither USN's notices.json nor DSA's data/DSA/list carries a usable
    # severity field — left None in practice for both sources today. See
    # docs/limitations.md. Kept as a real column (not omitted) so a future
    # NVD/CVSS cross-reference against `cves` can populate it without a
    # schema change.
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    packages: Mapped[list["ErratumPackage"]] = relationship(
        "ErratumPackage", cascade="all, delete-orphan"
    )


class ErratumPackage(Base):
    """One row per (erratum, release, package, fixed_version) — the queryable
    "which package versions does this advisory touch" data that
    Erratum.cves/title alone can't answer. Indexed on package_name since
    GET /errata/{id}/affected-servers joins on it against every server's
    latest installed-package facts.
    """

    __tablename__ = "erratum_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    erratum_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("errata.id"), nullable=False)
    release: Mapped[str] = mapped_column(String, nullable=False)
    package_name: Mapped[str] = mapped_column(String, nullable=False)
    fixed_version: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("ix_erratum_packages_package_name", "package_name"),)


class HostGroup(Base):
    __tablename__ = "host_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Inherited by a NEW self-registering server (via an ActivationKey that
    # references this group) at creation time only — never retroactively
    # applied to an existing server's environment_id. See enrollment.py.
    default_environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lifecycle_environments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    servers: Mapped[list["Server"]] = relationship("Server", secondary="host_group_servers")


class HostGroupServer(Base):
    __tablename__ = "host_group_servers"

    host_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("host_groups.id"), primary_key=True
    )
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("servers.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class JobServer(Base):
    """Resolved target-server set at dispatch time — the audit source of
    truth for "what ran against which hosts," independent of later host
    group membership changes. Written once by the triggering router for
    every job type, including bootstrap/apply_updates/gather_facts.
    """

    __tablename__ = "job_servers"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("servers.id"), primary_key=True)

    __table_args__ = (Index("ix_job_servers_server_id", "server_id"),)


class ActivationKey(Base):
    """DB-backed enrollment token — Satellite activation-key equivalent.
    Only a hash of the token is stored (same posture as User.hashed_password);
    the raw token is returned exactly once, at creation, and never again.
    """

    __tablename__ = "activation_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lifecycle_environments.id"), nullable=False
    )
    host_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("host_groups.id"), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ServerFact(Base):
    """Append-only host-facts history — same shape/posture as
    ComplianceRecord, but scoped to general facts (OS/kernel/uptime/disk/
    services) rather than packages. Package facts stay in ComplianceRecord
    unchanged; gather_facts_task writes both from the same playbook run.
    """

    __tablename__ = "server_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=False)
    os_distribution: Mapped[str | None] = mapped_column(String, nullable=True)
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    kernel: Mapped[str | None] = mapped_column(String, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{"mount": "/", "size_total_mb": int, "size_available_mb": int}, ...]
    disk: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{"name": "nginx", "state": "running", "status": "enabled"}, ...]
    services: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gathered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_server_facts_server_id_gathered_at", "server_id", "gathered_at"),)


class Site(Base):
    """A physical/network location served by at most one Relay (this phase
    doesn't model multi-relay-per-site HA/load-balancing — see
    docs/relays.md). Servers reference a Site to route bootstrap URLs and
    Ansible job execution through that site's Relay, falling back to the
    primary when no Relay exists or it's unhealthy/stale.
    """

    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Relay(Base):
    """A thin remote node (aptly + nginx, no Postgres, no control plane —
    see ROADMAP.md Phase 5) that mirrors a subset of the primary's
    published content and serves it to its site's hosts over LAN. Holds no
    authoritative state of its own; rebuildable from scratch by re-syncing.
    One relay per site in this phase (site_id is unique).
    """

    __tablename__ = "relays"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String, nullable=False)
    ssh_user: Mapped[str] = mapped_column(String, nullable=False)
    sync_status: Mapped[RelaySyncStatus] = mapped_column(
        Enum(RelaySyncStatus, name="relay_sync_status"), nullable=False, default=RelaySyncStatus.never_synced
    )
    last_sync_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SiteEnvironment(Base):
    """Explicit selective-sync allowlist: which LifecycleEnvironments a
    site's relay should carry. Explicit join table (not derived from
    "any environment with a server at this site") so a site can be
    provisioned ahead of any server actually being registered there —
    matches this codebase's preference for explicit, auditable
    configuration over implicit derived state (see HostGroupServer).
    """

    __tablename__ = "site_environments"

    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), primary_key=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lifecycle_environments.id"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Branding(Base):
    """Instance-wide UI branding — single shared row (id fixed to a
    well-known constant, enforced by the router never inserting a second
    row), not per-user. Matches how the sidebar/theme looks the same for
    every user today; this just makes it admin-editable instead of
    hardcoded. Logo/favicon bytes live here rather than on disk — the only
    stateful store this app otherwise has is Postgres (see
    docs/backup.md — the existing pg_dump-based backup covers this with
    no changes), and a filesystem path would need install.sh/
    groundctl-maintain/backup.sh to all learn about a new directory.
    """

    __tablename__ = "branding"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    primary_color: Mapped[str | None] = mapped_column(String, nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    favicon_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    favicon_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
