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
#   sudo groundctl-maintain upgrade
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
    load_conf
    local repo_root="${GROUNDCTL_REPO_ROOT}"
    cd "${repo_root}"

    local before_version after_version
    before_version="$(cat VERSION 2>/dev/null || echo unknown)"

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
    if [[ "${before_version}" == "${after_version}" ]]; then
        log_info "already up to date (v${after_version})."
        return
    fi
    log_info "upgrading v${before_version} -> v${after_version}"

    # Source the SAME shared library functions install.sh uses — direct
    # reuse of already-idempotent provisioning logic, not a shell-out to
    # install.sh and not a second implementation of it.
    REPO_ROOT="${repo_root}"
    # shellcheck source=scripts/lib/os.sh
    . "${REPO_ROOT}/scripts/lib/os.sh"
    # shellcheck source=scripts/lib/app.sh
    . "${REPO_ROOT}/scripts/lib/app.sh"

    detect_os
    log_info "updating apt package index..."
    apt-get update -qq
    install_app_prereqs
    install_node_prereqs

    build_ui
    sync_app_code
    setup_venv
    run_migrations
    install_groundctl_service
    install_groundctl_worker_service
    install_groundctl_beat_service
    install_maintain_script  # keep /usr/local/bin/groundctl-maintain itself current

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
  upgrade      Pull the latest released version (main) and apply it:
               rebuilds the web UI, resyncs app code, updates Python
               deps, applies pending database migrations, and restarts
               groundctl/worker/beat.
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
