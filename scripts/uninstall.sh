#!/usr/bin/env bash
#
# Tears down everything install.sh sets up, so a re-run of install.sh is a
# genuine fresh install rather than picking up leftover state. Standalone,
# not sourced by install.sh — this is an explicit, rarely-run operator
# action, never something another script should invoke on your behalf.
#
# Destroys: the groundctl Postgres database and role, /opt/groundctl,
# /etc/groundctl, /var/lib/groundctl (aptly's mirror/snapshot/published
# pool — irrecoverable unless you have a backup, see scripts/backup.sh),
# the groundctl/groundctl-sync system users, and the systemd units
# install.sh templated in. Also purges and reinstalls the redis-server
# package itself, clearing any stuck state (bad RDB dump, systemd
# supervision mismatch, etc) that a config-level fix can't reach.
#
# Does NOT remove the postgresql/nginx/redis-server/openssh-server
# *packages* (redis-server is the one exception — see above) — only
# groundctl's own config/data layered on top of them. Re-run install.sh
# after this to reinstall clean.
#
# Usage:
#   sudo ./scripts/uninstall.sh --yes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=scripts/lib/os.sh
. "${REPO_ROOT}/scripts/lib/os.sh"

confirm_or_die() {
    if [[ "${1:-}" != "--yes" ]]; then
        cat >&2 <<'EOF'
This PERMANENTLY DESTROYS the groundctl database, all aptly mirror/
snapshot/published data, and every groundctl config file on this host.
There is no undo unless you have a backup (see scripts/backup.sh).

Re-run with --yes to proceed:
  sudo ./scripts/uninstall.sh --yes
EOF
        exit 1
    fi
}

stop_services() {
    log_info "stopping groundctl services..."
    systemctl stop groundctl groundctl-worker groundctl-beat aptly redis-server nginx 2>/dev/null || true
    systemctl disable groundctl groundctl-worker groundctl-beat aptly redis-server 2>/dev/null || true
}

drop_database() {
    if ! systemctl is-active --quiet postgresql; then
        log_warn "postgresql isn't running — skipping database/role drop"
        return
    fi
    log_info "dropping postgres database and role..."
    (cd /tmp && sudo -u postgres psql -c "DROP DATABASE IF EXISTS groundctl;") >/dev/null
    (cd /tmp && sudo -u postgres psql -c "DROP ROLE IF EXISTS groundctl;") >/dev/null
}

remove_directories() {
    log_info "removing /opt/groundctl, /etc/groundctl, /var/lib/groundctl..."
    rm -rf /opt/groundctl /etc/groundctl /var/lib/groundctl
}

remove_users() {
    log_info "removing service users..."
    userdel -r groundctl 2>/dev/null || true
    userdel -r groundctl-sync 2>/dev/null || true
}

reset_redis() {
    log_info "purging and reinstalling redis-server (clears any stuck state)..."
    systemctl stop redis-server 2>/dev/null || true
    apt-get purge -y redis-server >/dev/null
    rm -rf /etc/redis /var/lib/redis
    apt-get install -y redis-server >/dev/null
    systemctl stop redis-server 2>/dev/null || true
    systemctl disable redis-server 2>/dev/null || true
}

remove_systemd_units() {
    log_info "removing groundctl systemd unit files..."
    rm -f /etc/systemd/system/groundctl.service
    rm -f /etc/systemd/system/groundctl-worker.service
    rm -f /etc/systemd/system/groundctl-beat.service
    rm -f /etc/systemd/system/aptly.service
    systemctl daemon-reload
}

main() {
    require_root
    confirm_or_die "${1:-}"

    stop_services
    drop_database
    remove_directories
    remove_users
    reset_redis
    remove_systemd_units

    log_info "done. Re-run: sudo ./install.sh"
}

main "$@"
