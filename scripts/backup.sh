#!/usr/bin/env bash
#
# Backup and restore for groundctl's two stateful stores: the Postgres
# database (all control-plane state) and /var/lib/groundctl (aptly's
# mirror/snapshot/published-package pool, plus the local GPG keyring used
# for signing — see docs/gpg-signing.md). Standalone, not part of
# install.sh — backup is an operational task run on a schedule or on
# demand, not an install-time step. See docs/backup.md for the full
# procedure, recommended schedule, and what this does NOT cover
# (point-in-time recovery via WAL archiving).
#
# Usage:
#   sudo ./scripts/backup.sh backup <dest-dir>
#   sudo ./scripts/backup.sh restore <dest-dir>/<timestamp> [--force]
#
# `restore` takes the same prefix `backup` printed on completion (both
# <prefix>.pgdump and <prefix>-var-lib-groundctl.tar.gz must exist).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=scripts/lib/os.sh
. "${REPO_ROOT}/scripts/lib/os.sh"
# shellcheck source=scripts/lib/pg.sh
. "${REPO_ROOT}/scripts/lib/pg.sh"

DATA_ROOT="/var/lib/groundctl"
PG_DB="groundctl"
PG_ROLE="groundctl"

do_backup() {
    local dest_dir="$1"
    [[ -n "${dest_dir}" ]] || die "backup requires a destination directory: ./scripts/backup.sh backup <dest-dir>"
    mkdir -p "${dest_dir}"

    local timestamp
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    local prefix="${dest_dir}/groundctl-backup-${timestamp}"

    log_info "dumping Postgres database '${PG_DB}'..."
    sudo -u postgres pg_dump -Fc -d "${PG_DB}" -f "${prefix}.pgdump"

    log_info "archiving ${DATA_ROOT}..."
    tar -czf "${prefix}-var-lib-groundctl.tar.gz" -C "$(dirname "${DATA_ROOT}")" "$(basename "${DATA_ROOT}")"

    log_info "backup complete:"
    log_info "  ${prefix}.pgdump"
    log_info "  ${prefix}-var-lib-groundctl.tar.gz"
    log_info "restore with: sudo ./scripts/backup.sh restore ${prefix}"
}

do_restore() {
    local prefix="$1"
    local force="${2:-}"
    [[ -n "${prefix}" ]] || die "restore requires a backup prefix: ./scripts/backup.sh restore <prefix> [--force]"

    local pgdump="${prefix}.pgdump"
    local archive="${prefix}-var-lib-groundctl.tar.gz"
    [[ -f "${pgdump}" ]] || die "not found: ${pgdump}"
    [[ -f "${archive}" ]] || die "not found: ${archive}"

    if [[ -d "${DATA_ROOT}" ]] && [[ -n "$(ls -A "${DATA_ROOT}" 2>/dev/null)" ]] && [[ "${force}" != "--force" ]]; then
        die "${DATA_ROOT} already has content — restore is destructive to whatever's there." \
            "Re-run with --force to proceed anyway."
    fi

    local role_exists
    role_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${PG_ROLE}'")
    if [[ "${role_exists}" != "1" ]]; then
        die "postgres role '${PG_ROLE}' does not exist — run install.sh first, or" \
            "ensure_postgres_role_and_db manually (scripts/lib/pg.sh) before restoring."
    fi

    if [[ "${force}" == "--force" ]]; then
        log_warn "dropping and recreating database '${PG_DB}' before restore"
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${PG_DB};" >/dev/null
        sudo -u postgres psql -c "CREATE DATABASE ${PG_DB} OWNER ${PG_ROLE};" >/dev/null
    fi

    log_info "restoring Postgres database '${PG_DB}' from ${pgdump}..."
    sudo -u postgres pg_restore -d "${PG_DB}" --clean --if-exists "${pgdump}"

    log_info "restoring ${DATA_ROOT} from ${archive}..."
    rm -rf "${DATA_ROOT}"
    tar -xzf "${archive}" -C "$(dirname "${DATA_ROOT}")"
    chown -R groundctl:groundctl "${DATA_ROOT}"

    log_info "restore complete. Restart groundctl services:"
    log_info "  systemctl restart groundctl groundctl-worker groundctl-beat aptly"
}

main() {
    require_root
    local action="${1:-}"
    case "${action}" in
        backup)
            do_backup "${2:-}"
            ;;
        restore)
            do_restore "${2:-}" "${3:-}"
            ;;
        *)
            echo "Usage: $0 backup <dest-dir> | restore <prefix> [--force]" >&2
            exit 1
            ;;
    esac
}

main "$@"
