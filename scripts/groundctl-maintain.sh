#!/usr/bin/env bash
#
# groundctl-maintain — standalone post-install operational command.
# Installed to /usr/local/bin by install.sh (scripts/lib/app.sh's
# install_maintain_script, first-install only).
#
# This is a SEPARATE script from install.sh, not a wrapper around it:
# install.sh is for first-time provisioning (run once, from inside a
# checkout, and for applying config changes like fleet hostname/nginx
# port afterward). groundctl-maintain is the standing command an operator
# runs afterward for day-to-day maintenance — `upgrade` and `regen-cert`.
#
# It sources the same scripts/lib/*.sh functions install.sh uses (direct
# reuse of already-idempotent provisioning logic) but never calls
# install.sh itself, and never touches one-time provisioning it doesn't
# explicitly opt into above (Postgres/Redis/aptly/nginx packages, the SSH
# keypair, the fleet hostname/port) — `upgrade` only touches what a code
# upgrade needs; `regen-cert` only touches the TLS cert, explicitly, on
# request. If you need to change the fleet hostname or nginx port, that's
# still install.sh's job, run from the checkout.
#
# Usage:
#   sudo groundctl-maintain upgrade [--force]
#   sudo groundctl-maintain regen-cert

set -euo pipefail

MAINTAIN_CONF="/etc/groundctl/maintain.conf"

log_info()  { echo "[groundctl-maintain] $*"; }
log_error() { echo "[groundctl-maintain] ERROR: $*" >&2; }
die()       { log_error "$*"; exit 1; }

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "must be run as root (try: sudo groundctl-maintain upgrade)"
    fi
}

load_conf() {
    [[ -r "${MAINTAIN_CONF}" ]] || die "no ${MAINTAIN_CONF} found — was groundctl installed via install.sh?"
    # shellcheck source=/dev/null
    . "${MAINTAIN_CONF}"
    [[ -n "${GROUNDCTL_REPO_ROOT:-}" ]] || die "${MAINTAIN_CONF} is missing GROUNDCTL_REPO_ROOT"
    [[ -d "${GROUNDCTL_REPO_ROOT}/.git" ]] || die "GROUNDCTL_REPO_ROOT (${GROUNDCTL_REPO_ROOT}) is not a git checkout"
}

cmd_upgrade() {
    require_root
    local force=0
    for arg in "$@"; do
        case "${arg}" in
            --force) force=1 ;;
            *) die "unknown option: ${arg} (see --help)" ;;
        esac
    done
    load_conf
    local repo_root="${GROUNDCTL_REPO_ROOT}"
    cd "${repo_root}"

    local before_version after_version before_commit after_commit
    before_version="$(cat VERSION 2>/dev/null || echo unknown)"
    before_commit="$(git rev-parse HEAD)"

    log_info "fetching latest release (origin/main)..."
    git fetch origin main --tags --quiet

    # main is the released/stable branch (see docs/releasing.md) —
    # release.yml only ever fast-forwards it, so a hard reset here can
    # never discard real work, only move to a newer point on the same
    # line of history this checkout's main already follows. Config lives
    # in /etc/groundctl/, not the checkout, so there's nothing local here
    # worth preserving across the reset.
    git checkout main --quiet
    git reset --hard origin/main --quiet

    after_version="$(cat VERSION 2>/dev/null || echo unknown)"
    after_commit="$(git rev-parse HEAD)"

    # Source the SAME shared library functions install.sh uses — direct
    # reuse of already-idempotent provisioning logic, not a shell-out to
    # install.sh and not a second implementation of it. tls.sh is required
    # here too: a real bug found live — install_groundctl_service (below,
    # via _install_app_service) has always referenced TLS_CERT_PATH/
    # TLS_KEY_PATH (only ever defined in tls.sh, never sourced here before)
    # to render groundctl.service.template. This silently never mattered
    # while `upgrade` only ever reached that code path on a genuine VERSION
    # bump immediately after a fresh install.sh run (which had already
    # sourced tls.sh in the same process) — the 0.12.1 fix that made
    # `upgrade` redeploy on any new commit, not just a version bump, is
    # what finally made a bare `groundctl-maintain upgrade` (no prior
    # install.sh in that process) hit this path for the first time and
    # fail with "TLS_CERT_PATH: unbound variable" under set -u.
    REPO_ROOT="${repo_root}"
    # shellcheck source=scripts/lib/os.sh
    . "${REPO_ROOT}/scripts/lib/os.sh"
    # shellcheck source=scripts/lib/app.sh
    . "${REPO_ROOT}/scripts/lib/app.sh"
    # shellcheck source=scripts/lib/tls.sh
    . "${REPO_ROOT}/scripts/lib/tls.sh"

    # Always reinstall groundctl-maintain itself, even when nothing else
    # changed — a real bug found live: this used to run only inside the
    # "something changed" branch below, gated on the VERSION diff. But a
    # checkout can already be sitting on the latest VERSION (e.g. from an
    # earlier partial/interrupted pull) while /usr/local/bin/
    # groundctl-maintain still has older *content* — VERSION doesn't bump
    # on every commit, so "no version change" does not mean "no script
    # change." Cheap (a single `install`) and idempotent either way.
    install_maintain_script

    # Also always re-render and re-check the systemd units — a third real
    # bug found live, same shape as install_maintain_script above but for
    # groundctl.service/-worker/-beat. These were gated behind the same
    # "did the commit move" check below, so a unit that went stale for a
    # reason OTHER than a code change (e.g. it was written before the
    # __GROUNDCTL_PORT__/tls.sh sourcing fix even existed) could never be
    # repaired by upgrade alone — only a full install.sh re-run would
    # unconditionally rewrite it, which is not what upgrade is for.
    # _install_app_service (scripts/lib/app.sh) already does its own
    # cheap content-diff internally (render to a temp file, cmp against
    # what's installed, only restart if it actually differs or the
    # service isn't running) — safe and cheap to call unconditionally,
    # exactly like install_maintain_script above.
    install_groundctl_service
    install_groundctl_worker_service
    install_groundctl_beat_service

    # Gate the expensive stuff (apt, npm ci, venv rebuild, migrations) on
    # the actual commit, not VERSION — a second real bug found live.
    # VERSION only bumps on a release; several ordinary commits (fixes,
    # features without a version bump yet) can land on main in between.
    # Gating the redeploy purely on "did VERSION change" meant a checkout
    # could genuinely pull new app code via git reset --hard, report
    # "already up to date" because VERSION hadn't moved, and skip
    # sync_app_code/service restart entirely — leaving groundctl.service
    # running the OLD code indefinitely, invisible until an operator
    # manually restarted it or went looking. HEAD is the actual "did
    # anything change" signal.
    if [[ "${before_commit}" == "${after_commit}" ]]; then
        if [[ "${force}" -eq 1 ]]; then
            # --force exists for exactly this: HEAD already matches
            # origin/main (an earlier upgrade/pull already moved the code)
            # but the redeploy itself never completed — e.g. build_ui was
            # interrupted, or code landed via a manual `git pull` instead
            # of `upgrade`, leaving ui/dist stale even though the checkout
            # is at the right commit. Real bug found live: "already up to
            # date" here means "HEAD didn't move THIS run," not "the
            # deployed artifacts are known-current" — those are different
            # claims, and only --force lets an operator act on the gap
            # between them without a no-op commit.
            log_info "already at v${after_version} (HEAD unchanged) — --force given, redeploying anyway"
        else
            log_info "already up to date (v${after_version})."
            return
        fi
    elif [[ "${before_version}" == "${after_version}" ]]; then
        log_info "new commits on main (v${after_version} unchanged) — redeploying app code and restarting services"
    else
        log_info "upgrading v${before_version} -> v${after_version}"
    fi

    detect_os
    log_info "updating apt package index..."
    apt-get update -qq
    install_app_prereqs
    install_node_prereqs

    build_ui
    sync_app_code
    setup_venv
    grant_bind_low_ports
    run_migrations
    # Units already (re-)installed unconditionally above, before this
    # gate — sync_app_code/setup_venv don't change anything the rendered
    # unit content depends on, so re-calling _install_app_service here
    # would just re-render identical content and no-op. What DOES need a
    # restart post-upgrade is the app code itself; that's what
    # ExecStart's running process picks up, not a re-render of the unit
    # file. Restart directly instead of going through
    # install_groundctl_service a second time.
    systemctl restart groundctl
    systemctl restart groundctl-worker
    systemctl restart groundctl-beat

    log_info "upgrade complete — now on v${after_version}."
}

cmd_regen_cert() {
    require_root
    load_conf
    local repo_root="${GROUNDCTL_REPO_ROOT}"
    local env_file="/etc/groundctl/groundctl.env"

    [[ -r "${env_file}" ]] || die "no ${env_file} found — was groundctl installed via install.sh?"

    # PUBLISHED_REPO_BASE_URL=https://<fleet_hostname>:<nginx_port> is the
    # single source of truth write_groundctl_env (scripts/lib/app.sh)
    # writes from those two inputs — parsed back out here rather than
    # stored a second time, same reasoning as groundctl-maintain upgrade's
    # (removed) fleet-hostname parsing.
    local fleet_hostname
    fleet_hostname="$(grep -E '^PUBLISHED_REPO_BASE_URL=' "${env_file}" | sed -E 's#.*https://([^:]+):.*#\1#')"
    [[ -n "${fleet_hostname}" ]] || die "could not determine fleet hostname from ${env_file}"

    # shellcheck source=scripts/lib/os.sh
    . "${repo_root}/scripts/lib/os.sh"
    # shellcheck source=scripts/lib/tls.sh
    . "${repo_root}/scripts/lib/tls.sh"

    if [[ ! -f "${TLS_CERT_PATH}" ]]; then
        log_info "no existing cert at ${TLS_CERT_PATH} — nothing to regenerate, run install.sh instead"
        return
    fi

    local backup_dir
    backup_dir="/etc/groundctl/tls/backup-$(date +%Y%m%d%H%M%S)"
    log_info "backing up existing cert to ${backup_dir} before regenerating"
    mkdir -p "${backup_dir}"
    cp -a "${TLS_CERT_PATH}" "${TLS_KEY_PATH}" "${backup_dir}/"

    _generate_tls_cert "${fleet_hostname}"

    log_info "restarting groundctl and nginx to pick up the new cert..."
    systemctl restart groundctl
    systemctl restart nginx

    log_info "TLS cert regenerated for ${fleet_hostname}."
    log_info "previous cert backed up at ${backup_dir} (safe to delete once you've confirmed the new one works)"
}

case "${1:-}" in
    upgrade)
        shift
        cmd_upgrade "$@"
        ;;
    regen-cert)
        shift
        cmd_regen_cert "$@"
        ;;
    -h|--help|"")
        cat <<'EOF'
Usage: groundctl-maintain <command>

Commands:
  upgrade [--force]
               Pull the latest released version (main) and apply it:
               rebuilds the web UI, resyncs app code, updates Python
               deps, applies pending database migrations, and restarts
               groundctl/worker/beat. Normally a no-op if HEAD is already
               at origin/main's commit. --force redeploys anyway — use
               this if the checkout is already at the right commit but
               the build/sync/restart itself is suspected stale (e.g. an
               earlier upgrade was interrupted).
  regen-cert   Regenerate the self-signed TLS cert (fleet hostname read
               back from /etc/groundctl/groundctl.env) and restart
               groundctl + nginx to pick it up. Backs up the old cert
               first. Use this after upgrading past a fix to how the
               cert is generated (e.g. a key-type change) — install.sh
               itself never overwrites an existing cert.

groundctl-maintain is separate from install.sh: install.sh is for
first-time provisioning and config changes (fleet hostname, nginx port),
run from inside a checkout. This command is what you run afterward for
code upgrades and TLS cert regeneration.
EOF
        ;;
    *)
        die "unknown command: $1 (see --help)"
        ;;
esac
