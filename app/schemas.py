import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, IPvAnyAddress, field_validator

from app.models import (
    AuditAction,
    ErratumSource,
    FilterType,
    JobStatus,
    JobTargetType,
    JobType,
    PackageAction,
    RelaySyncStatus,
    Role,
    ServerLifecycleState,
    ServerStatus,
)

APTLY_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
SOURCES_LIST_FIELD_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
# Debian Policy Manual §5.6.7: lowercase alphanumerics plus +-., must start
# with an alphanumeric. Distinct from APTLY_NAME_RE, which is about aptly
# *object* names (mirrors/snapshots), not real Debian package names.
DEBIAN_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
# RFC 1123 hostname shape — closes a pre-existing gap (hostname previously
# had no validator despite flowing into the Ansible inventory dict key, and
# now also into the attacker-influenced self-registration path).
HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
# Uppercase hex GPG fingerprint (gpg --export uses long-form 40-char, but
# accept 16-40 to allow a short key ID too) — used directly in a `gpg
# --export --armor <key_id>` subprocess call, so this is an injection
# boundary, not just a shape check.
GPG_KEY_ID_RE = re.compile(r"^[A-F0-9]{16,40}$")
# #RGB or #RRGGBB — CSS custom properties (see ui/'s index.css tokens) get
# these values injected directly; strict validation here means the
# frontend never needs to defend against a malformed value reaching the
# DOM as an inline style.
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def validate_hex_color(v: str) -> str:
    if not HEX_COLOR_RE.fullmatch(v):
        raise ValueError("must be a hex color, e.g. #0F6CBD or #0F6")
    return v


def validate_gpg_key_id(v: str) -> str:
    if not GPG_KEY_ID_RE.fullmatch(v):
        raise ValueError("must be an uppercase hex GPG key ID/fingerprint, 16-40 characters")
    return v


def validate_aptly_name(v: str) -> str:
    if not APTLY_NAME_RE.fullmatch(v):
        raise ValueError(
            "must match ^[a-zA-Z0-9._-]+$ (aptly object name — used directly in aptly API paths)"
        )
    return v


def validate_sources_list_field(v: str) -> str:
    if not SOURCES_LIST_FIELD_RE.fullmatch(v):
        raise ValueError(
            "must match ^[a-zA-Z0-9._-]+$ (interpolated into a sources.list deb line on managed hosts)"
        )
    return v


def validate_debian_package_name(v: str) -> str:
    if not DEBIAN_PACKAGE_NAME_RE.fullmatch(v):
        raise ValueError(
            "must be a valid Debian package name: lowercase alphanumerics, '+', '-', '.', "
            "starting with an alphanumeric (Debian Policy Manual §5.6.7)"
        )
    return v


def validate_hostname(v: str) -> str:
    if len(v) > 253 or not HOSTNAME_RE.fullmatch(v):
        raise ValueError("must be a valid DNS hostname")
    return v


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: Role = Role.viewer


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr
    role: Role
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    # username is intentionally not editable here — it's the JWT subject
    # (create_access_token's "sub" claim) and the login identifier; renaming
    # it would invalidate every outstanding token for that user with no
    # graceful transition. Email/role changes don't have that problem.
    email: EmailStr | None = None
    role: Role | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UIAccessToken(BaseModel):
    # Used by the web UI's cookie-based auth flow — the refresh token is
    # never present in this body, only in the httpOnly cookie set alongside
    # it (see /auth/ui-login).
    access_token: str
    token_type: str = "bearer"


class AuditLogRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: AuditAction
    resource_type: str
    resource_id: str | None
    detail: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


class ProductCreate(BaseModel):
    name: str
    description: str | None = None

    _validate_name = field_validator("name")(validate_aptly_name)


class ProductRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    # Count of repositories currently assigned — computed by the router
    # (a join/count, not a stored column), same reasoning as
    # RepositoryRead.health_status.
    repository_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductUpdate(BaseModel):
    name: str
    description: str | None = None

    _validate_name = field_validator("name")(validate_aptly_name)


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------


class RepositoryCreate(BaseModel):
    name: str
    archive_url: HttpUrl
    distribution: str
    components: list[str]
    architectures: list[str]

    _validate_name = field_validator("name")(validate_aptly_name)
    _validate_distribution = field_validator("distribution")(validate_aptly_name)

    @field_validator("components")
    @classmethod
    def _validate_components(cls, v: list[str]) -> list[str]:
        return [validate_aptly_name(item) for item in v]


class RepositoryRead(BaseModel):
    id: uuid.UUID
    name: str
    archive_url: HttpUrl
    distribution: str
    components: list[str]
    architectures: list[str]
    # NULL = ungrouped. See Product's docstring — purely organizational,
    # never affects sync/publish/content-view behavior.
    product_id: uuid.UUID | None
    last_synced_at: datetime | None
    # Actual on-disk package size aptly reports as of last_synced_at (see
    # AptlyClient.get_mirror_size_bytes) — null until the first successful
    # sync_repository job completes.
    size_bytes: int | None
    # Package count from that same sync pass — null under the identical
    # condition as size_bytes (never synced yet).
    package_count: int | None
    # Computed, not a stored column — "never_synced" if last_synced_at is
    # null, "stale" if it's older than InstanceSetting's
    # repository_stale_threshold_hours (admin-configurable, Settings >
    # System), "healthy" otherwise. Display-only: unlike the server/relay
    # staleness sweeps, nothing schedules off this or fires a webhook for
    # it — set explicitly by the router (not a plain from_attributes
    # mapping) since computing it needs that threshold at read time.
    health_status: Literal["healthy", "stale", "never_synced"]
    last_sync_job_id: uuid.UUID | None
    # Most recent Job of any kind (sync/update/delete) — unlike
    # last_sync_job_id above, tracks Edit/Delete too, so the UI can restore
    # live status for whichever action was running after a page reload,
    # not just Sync.
    last_job_id: uuid.UUID | None
    # Whether the nightly scheduled sweep (scheduled_sync_all_repositories,
    # app/tasks.py) includes this repository — defaults True on creation.
    # Manual sync (POST .../sync) always works regardless of this flag.
    auto_sync_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RepositoryProductUpdate(BaseModel):
    # None = ungroup (remove from whatever Product it's currently in).
    product_id: uuid.UUID | None = None


class RepositoryAutoSyncUpdate(BaseModel):
    auto_sync_enabled: bool


class RepositoryUpdate(BaseModel):
    """Aptly mirrors can't change ArchiveURL/Distribution/Components in
    place — there is no PUT-equivalent in aptly's own API. "Editing" a
    repository here means delete-then-recreate the underlying aptly mirror
    under the same Repository row (same id, same name), so every foreign
    key pointing at this repository (ContentViewRepository, Job.repository_id)
    stays valid. Guarded the same way delete is: refused with 409 if any
    ContentView currently references this repository, since swapping the
    mirror's source data out from under a referenced repository is exactly
    the kind of instability CLAUDE.md's snapshot-immutability invariant
    warns against.
    """

    archive_url: HttpUrl
    distribution: str
    components: list[str]
    architectures: list[str]

    _validate_distribution = field_validator("distribution")(validate_aptly_name)

    @field_validator("components")
    @classmethod
    def _validate_components(cls, v: list[str]) -> list[str]:
        return [validate_aptly_name(item) for item in v]


class RepositoryProbeRequest(BaseModel):
    archive_url: HttpUrl


class RepositoryProbeResult(BaseModel):
    distributions: list[str]


class RepositoryEstimateSizeRequest(BaseModel):
    archive_url: HttpUrl
    distribution: str
    components: list[str]
    architectures: list[str]

    _validate_distribution = field_validator("distribution")(validate_aptly_name)

    @field_validator("components")
    @classmethod
    def _validate_components(cls, v: list[str]) -> list[str]:
        return [validate_aptly_name(item) for item in v]


class RepositoryEstimateSizeResult(BaseModel):
    size_bytes: int


class RepositoryBatchCreate(BaseModel):
    """Creates one Repository (aptly mirror) per selected distribution, all
    sharing the same archive_url/components/architectures — the backend for
    the "browse an archive, multi-select distributions" UI flow. Each
    resulting repository is named after its distribution (e.g. "jammy",
    "jammy-updates") — same aptly object name uniqueness rules as the
    single-repository endpoint, so a name collision surfaces as a per-item
    error in RepositoryBatchCreateResult rather than failing the batch.
    """

    archive_url: HttpUrl
    distributions: list[str] = Field(min_length=1)
    components: list[str]
    architectures: list[str]

    @field_validator("distributions")
    @classmethod
    def _validate_distributions(cls, v: list[str]) -> list[str]:
        return [validate_aptly_name(item) for item in v]

    @field_validator("components")
    @classmethod
    def _validate_batch_components(cls, v: list[str]) -> list[str]:
        return [validate_aptly_name(item) for item in v]


class RepositoryBatchCreateError(BaseModel):
    distribution: str
    detail: str


class RepositoryBatchCreateResult(BaseModel):
    created: list[RepositoryRead]
    errors: list[RepositoryBatchCreateError]


# ---------------------------------------------------------------------------
# content views
# ---------------------------------------------------------------------------


class ContentViewCreate(BaseModel):
    name: str
    repository_ids: list[uuid.UUID] = Field(min_length=1)

    _validate_name = field_validator("name")(validate_aptly_name)


class ContentViewRead(BaseModel):
    id: uuid.UUID
    name: str
    repository_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class ContentViewVersionSnapshot(BaseModel):
    repository_id: uuid.UUID
    repository_name: str
    snapshot_name: str
    component: str


class ContentViewVersionRead(BaseModel):
    id: uuid.UUID
    content_view_id: uuid.UUID
    version: int
    snapshots: list[ContentViewVersionSnapshot]
    content_hash: str
    # Total packages across this version's final (post-filter) snapshots —
    # null only for versions cut before this field existed.
    package_count: int | None
    published_at: datetime

    model_config = {"from_attributes": True}


class PublishResponse(BaseModel):
    content_view_version: ContentViewVersionRead
    version_cut: bool


# A package name or a simple wildcard/regex pattern, per aptly's query
# grammar this eventually feeds (see AptlyClient.create_filtered_snapshot).
# Deliberately more permissive than validate_aptly_name (needs to allow *,
# |, etc.) but still rejects whitespace/control characters — the value only
# ever reaches aptly via httpx's json= kwarg (never shell-interpolated), so
# this is a sanity bound, not an injection defense in the shell sense.
CONTENT_VIEW_FILTER_PATTERN_RE = re.compile(r"^[\x21-\x7e]+$")


class ContentViewFilterCreate(BaseModel):
    filter_type: FilterType
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str) -> str:
        if not CONTENT_VIEW_FILTER_PATTERN_RE.fullmatch(v):
            raise ValueError("pattern must contain only printable non-whitespace ASCII characters")
        return v

    @field_validator("pattern")
    @classmethod
    def _validate_errata_since_is_a_date(cls, v: str, info) -> str:
        # For errata_since filters, pattern must additionally parse as an
        # ISO date (e.g. "2026-01-01") — the printable-ASCII check above
        # already allows the required characters, this adds the semantic check.
        if info.data.get("filter_type") == FilterType.errata_since:
            try:
                date.fromisoformat(v)
            except ValueError as exc:
                raise ValueError("errata_since pattern must be an ISO date, e.g. 2026-01-01") from exc
        return v


class ContentViewFilterRead(BaseModel):
    id: uuid.UUID
    content_view_id: uuid.UUID
    filter_type: FilterType
    pattern: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# lifecycle environments
# ---------------------------------------------------------------------------


class LifecycleEnvironmentCreate(BaseModel):
    name: str
    path_name: str
    position: int = Field(ge=0)
    content_view_id: uuid.UUID
    distro: str
    release: str
    publish_prefix: str
    # GPG signing is on-by-default per CLAUDE.md: gpg_key_id is required
    # unless allow_unsigned is explicitly set, which is the documented,
    # logged opt-out (see docs/gpg-signing.md) — not silently permitted.
    gpg_key_id: str | None = None
    # validate_default=True: without it, pydantic v2 skips field validators
    # entirely for a field left at its default (allow_unsigned omitted from
    # the request body is the exact case this check exists for) — a real
    # bug caught by live verification, since the omitted-field case is the
    # one that matters most here.
    allow_unsigned: bool = Field(default=False, validate_default=True)

    _validate_name = field_validator("name")(validate_aptly_name)
    _validate_release = field_validator("release")(validate_sources_list_field)
    _validate_publish_prefix = field_validator("publish_prefix")(validate_sources_list_field)
    _validate_gpg_key_id = field_validator("gpg_key_id")(
        lambda v: validate_gpg_key_id(v) if v is not None else v
    )

    @field_validator("allow_unsigned")
    @classmethod
    def _validate_signing_choice(cls, v: bool, info) -> bool:
        if not v and info.data.get("gpg_key_id") is None:
            raise ValueError(
                "gpg_key_id is required unless allow_unsigned=true is explicitly set "
                "(see docs/gpg-signing.md)"
            )
        return v


class LifecycleEnvironmentRead(BaseModel):
    id: uuid.UUID
    name: str
    path_name: str
    position: int
    content_view_id: uuid.UUID
    distro: str
    release: str
    publish_prefix: str
    current_version_id: uuid.UUID | None
    gpg_key_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromoteRequest(BaseModel):
    # Omit to promote the content view's latest version.
    content_view_version_id: uuid.UUID | None = None


class PromoteResponse(BaseModel):
    id: uuid.UUID
    current_version_id: uuid.UUID
    publish_prefix: str
    published_url: str


class RollbackRequest(BaseModel):
    content_view_version_id: uuid.UUID


# ---------------------------------------------------------------------------
# servers
# ---------------------------------------------------------------------------


class ServerCreate(BaseModel):
    hostname: str
    ip_address: IPvAnyAddress
    ssh_user: str
    environment_id: uuid.UUID
    site_id: uuid.UUID | None = None

    _validate_hostname = field_validator("hostname")(validate_hostname)


class ServerRead(BaseModel):
    id: uuid.UUID
    hostname: str
    ip_address: str
    ssh_user: str
    environment_id: uuid.UUID
    site_id: uuid.UUID | None
    status: ServerStatus
    lifecycle_state: ServerLifecycleState
    last_seen_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ServerFactRead(BaseModel):
    server_id: uuid.UUID
    os_distribution: str | None
    os_version: str | None
    kernel: str | None
    uptime_seconds: int | None
    disk: list[dict]
    services: list[dict]
    gathered_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# sites / relays
# ---------------------------------------------------------------------------


class SiteCreate(BaseModel):
    name: str
    description: str | None = None

    _validate_name = field_validator("name")(validate_aptly_name)


class SiteUpdate(BaseModel):
    name: str
    description: str | None = None

    _validate_name = field_validator("name")(validate_aptly_name)


class SiteRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RelayCreate(BaseModel):
    hostname: str
    ssh_user: str

    _validate_hostname = field_validator("hostname")(validate_hostname)


class RelayRead(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    hostname: str
    ssh_user: str
    sync_status: RelaySyncStatus
    last_sync_time: datetime | None
    content_size_bytes: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SiteEnvironmentsUpdate(BaseModel):
    environment_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# host groups
# ---------------------------------------------------------------------------


class HostGroupCreate(BaseModel):
    name: str
    description: str | None = None
    default_environment_id: uuid.UUID | None = None

    _validate_name = field_validator("name")(validate_aptly_name)


class HostGroupRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    default_environment_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HostGroupMembershipUpdate(BaseModel):
    server_ids: list[uuid.UUID] = Field(min_length=1)


# ---------------------------------------------------------------------------
# activation keys / self-registration
# ---------------------------------------------------------------------------


class ActivationKeyCreate(BaseModel):
    name: str
    environment_id: uuid.UUID
    host_group_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)

    _validate_name = field_validator("name")(validate_aptly_name)


class ActivationKeyCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    # Raw token — returned exactly once, here, and never again.
    token: str
    environment_id: uuid.UUID
    host_group_id: uuid.UUID | None
    tags: list[str]
    expires_at: datetime | None
    max_uses: int | None


class ActivationKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    environment_id: uuid.UUID
    host_group_id: uuid.UUID | None
    tags: list[str]
    expires_at: datetime | None
    max_uses: int | None
    use_count: int
    revoked: bool
    created_at: datetime

    # token/token_hash deliberately absent — never serialized after creation.
    model_config = {"from_attributes": True}


class SelfRegisterRequest(BaseModel):
    token: str
    hostname: str
    ip_address: IPvAnyAddress
    ssh_user: str

    _validate_hostname = field_validator("hostname")(validate_hostname)


class SelfRegisterResponse(BaseModel):
    server_id: uuid.UUID
    environment_id: uuid.UUID
    hostname: str


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


class JobRead(BaseModel):
    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    target_type: JobTargetType
    server_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    host_group_id: uuid.UUID | None
    repository_id: uuid.UUID | None
    # Resolved target-server set — assembled by the router from JobServer
    # rows before returning, not an ORM relationship auto-load.
    server_ids: list[uuid.UUID] = Field(default_factory=list)
    log_output: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class BulkTargetSelector(BaseModel):
    """Shared targeting shape for bulk/ad-hoc job triggers. Exactly one of
    host_group_id / server_ids must be set — enforced in the router (needs
    both fields present to compare, awkward as a single-field validator)."""

    host_group_id: uuid.UUID | None = None
    server_ids: list[uuid.UUID] | None = None

    @field_validator("server_ids")
    @classmethod
    def _non_empty(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is not None and len(v) == 0:
            raise ValueError("server_ids must be non-empty if provided")
        return v


class BulkApplyUpdatesRequest(BulkTargetSelector):
    pass


class RunCommandRequest(BulkTargetSelector):
    command: str = Field(min_length=1, max_length=1024)

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        # Process-level mitigation, not a syntax whitelist — arbitrary
        # commands can't be regex-validated the way aptly names can (see
        # CLAUDE.md's injection-surface rule, docs/limitations.md). This
        # rejects shell metacharacters as defense-in-depth even though
        # ansible.builtin.command never invokes a shell (run_command.yml) —
        # rejecting avoids "why didn't my pipe/redirect work" confusion.
        if any(ch in v for ch in ";|&$`\n\r<>"):
            raise ValueError(
                "command must not contain shell metacharacters (; | & $ ` newlines <>) — "
                "ansible.builtin.command does not use a shell, so these would be passed "
                "literally as arguments, not interpreted; rejecting avoids confusing behavior"
            )
        return v


class ManagePackageRequest(BaseModel):
    server_id: uuid.UUID
    package_name: str
    action: PackageAction

    _validate_package_name = field_validator("package_name")(validate_debian_package_name)


# ---------------------------------------------------------------------------
# package search
# ---------------------------------------------------------------------------


class PackageSearchResult(BaseModel):
    server_id: uuid.UUID
    hostname: str
    installed_version: str


class PackageSearchResponse(BaseModel):
    package_name: str
    operator: str | None
    compare_version: str | None
    matches: list[PackageSearchResult]


# ---------------------------------------------------------------------------
# compliance
# ---------------------------------------------------------------------------


class PackageDrift(BaseModel):
    name: str
    installed_version: str | None
    available_version: str | None
    status: Literal["outdated", "up_to_date", "not_in_environment"]


class ComplianceCheckResult(BaseModel):
    server_id: uuid.UUID
    checked_at: datetime
    drift: list[PackageDrift]


# ---------------------------------------------------------------------------
# trends
# ---------------------------------------------------------------------------


class JobTrendPoint(BaseModel):
    date: date
    success: int
    failed: int
    running: int
    pending: int


class ComplianceTrendPoint(BaseModel):
    date: date
    outdated: int
    up_to_date: int
    checks: int


# ---------------------------------------------------------------------------
# version check
# ---------------------------------------------------------------------------


class VersionRead(BaseModel):
    current_version: str
    latest_version: str | None
    # True only when latest_version is known and strictly newer than
    # current_version — never true while latest_version is None (an
    # unreachable/never-run check must not imply "you're up to date" OR
    # "an update exists"; it implies nothing).
    update_available: bool
    last_checked_at: datetime | None


# ---------------------------------------------------------------------------
# errata
# ---------------------------------------------------------------------------


class ErratumPackageRead(BaseModel):
    release: str
    package_name: str
    fixed_version: str

    model_config = {"from_attributes": True}


class ErratumRead(BaseModel):
    id: uuid.UUID
    advisory_id: str
    source: ErratumSource
    title: str
    cves: list[str]
    severity: str | None
    published_at: datetime
    packages: list[ErratumPackageRead]

    model_config = {"from_attributes": True}


class AffectedServer(BaseModel):
    server_id: uuid.UUID
    hostname: str
    package_name: str
    installed_version: str
    fixed_version: str


class AffectedServersResponse(BaseModel):
    advisory_id: str
    affected: list[AffectedServer]


# ---------------------------------------------------------------------------
# docs
# ---------------------------------------------------------------------------


class DocSummary(BaseModel):
    filename: str
    title: str


class DocRead(BaseModel):
    filename: str
    title: str
    content: str


# ---------------------------------------------------------------------------
# branding
# ---------------------------------------------------------------------------


class BrandingRead(BaseModel):
    primary_color: str | None
    accent_color: str | None
    # Booleans, not the bytes themselves — GET /branding is read by every
    # authenticated user on every page load to decide what colors to apply;
    # the actual logo/favicon bytes are fetched separately (GET
    # /branding/logo, /branding/favicon), each cacheable independently by
    # the browser instead of re-downloading on every branding poll.
    has_logo: bool
    has_favicon: bool
    # None means no admin has configured anything yet (no row exists at
    # all) — genuinely distinct from "configured, most recently at time X".
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class BrandingColorsUpdate(BaseModel):
    # None explicitly clears back to the built-in default — distinguished
    # from "field omitted" via exclude_unset in the router, same pattern
    # PATCH-style partial updates use elsewhere in this file.
    primary_color: str | None = None
    accent_color: str | None = None

    _validate_primary = field_validator("primary_color")(
        lambda v: validate_hex_color(v) if v is not None else v
    )
    _validate_accent = field_validator("accent_color")(
        lambda v: validate_hex_color(v) if v is not None else v
    )


# ---------------------------------------------------------------------------
# instance settings
# ---------------------------------------------------------------------------


class InstanceSettingsRead(BaseModel):
    audit_log_retention_days: int
    activation_key_default_ttl_hours: int
    stale_checkin_hours: int
    relay_stale_threshold_hours: int
    repository_stale_threshold_hours: int
    disk_usage_warn_percent: float
    webhook_url: str | None
    # Deliberately excluded: webhook_secret is write-only, same posture as
    # a password hash or JWT (see CLAUDE.md's AuthN/AuthZ rules) — once
    # set, the API never echoes it back. has_webhook_secret tells the UI
    # whether one is currently configured without exposing its value.
    has_webhook_secret: bool
    # Per field, whether the value shown is a DB override or the
    # config.py/env-var default — lets the UI show "(default)" next to
    # unconfigured fields instead of a bare number.
    overridden: dict[str, bool]
    updated_at: datetime | None


class InstanceSettingsUpdate(BaseModel):
    # None means "clear the override, revert to config.py default" —
    # distinguished from "field omitted" via exclude_unset in the router,
    # same pattern as BrandingColorsUpdate above.
    audit_log_retention_days: int | None = None
    activation_key_default_ttl_hours: int | None = None
    stale_checkin_hours: int | None = None
    relay_stale_threshold_hours: int | None = None
    repository_stale_threshold_hours: int | None = None
    disk_usage_warn_percent: float | None = None
    webhook_url: str | None = None
    # Same None-clears/omitted-leaves-unchanged semantics — but note
    # "clear" here also has to erase the DB value outright, not just fall
    # back to config.py's own webhook_secret env var, since a
    # previously-set secret must actually become unset, not fall through
    # to a possibly-stale env-var secret. The router enforces this
    # distinction explicitly (see update_instance_settings).
    webhook_secret: str | None = None

    @field_validator(
        "audit_log_retention_days",
        "activation_key_default_ttl_hours",
        "stale_checkin_hours",
        "relay_stale_threshold_hours",
    )
    @classmethod
    def _validate_positive_int(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("must be a positive number of hours/days")
        return v

    @field_validator("repository_stale_threshold_hours")
    @classmethod
    def _validate_non_negative_int(cls, v: int | None) -> int | None:
        # Unlike the sibling thresholds above, 0 is a legitimate value here
        # — "flag as stale immediately once synced" (see
        # _repository_health_status in repositories.py, which already
        # special-cases stale_threshold_hours <= 0). Only reject negative.
        if v is not None and v < 0:
            raise ValueError("must be zero or a positive number of hours")
        return v

    @field_validator("disk_usage_warn_percent")
    @classmethod
    def _validate_percent(cls, v: float | None) -> float | None:
        if v is not None and not (0 < v <= 100):
            raise ValueError("must be between 0 and 100")
        return v
