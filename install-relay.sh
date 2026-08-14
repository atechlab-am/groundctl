#!/usr/bin/env bash
#
# Native installer for a groundctl Relay — a thin remote node (nginx +
# sshd only, no Postgres, no aptly, no FastAPI app, no control plane) that
# receives a subset of the primary's published content via rsync and
# serves it to its site's hosts. See ROADMAP.md Phase 5 and docs/relays.md.
#
# This is a SIBLING to install.sh, not a mode flag on it — install.sh is
# one long linear sequence assuming the full primary stack (Postgres,
# Redis, FastAPI, Celery worker+beat, JWT secret); a relay needs almost
# none of that, so a smaller dedicated script is clearer than threading
# conditionals through install.sh's provisioning functions.
#
# ASSUMPTION: must be run from inside a checked-out copy of this repo
# (./install-relay.sh from repo root) on the RELAY host itself.
#
# Usage:
#   sudo ./install-relay.sh [--nginx-port PORT] --primary-key-file PATH
#
# --primary-key-file must point at the PRIMARY's
# /etc/groundctl/ansible-keys/id_ed25519.pub contents (copy it over
# out-of-band — there is no automated key-exchange mechanism in this phase).
#
# After this completes, register the relay with the primary:
#   POST /sites, POST /sites/{id}/relay {"hostname": "<this-host>", "ssh_user": "groundctl-sync"}
#
# See docs/relays.md for the full walkthrough.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/lib/os.sh
. "${REPO_ROOT}/scripts/lib/os.sh"
# shellcheck source=scripts/lib/systemd.sh
. "${REPO_ROOT}/scripts/lib/systemd.sh"
# shellcheck source=scripts/lib/relay.sh
. "${REPO_ROOT}/scripts/lib/relay.sh"
# shellcheck source=scripts/lib/tls.sh
. "${REPO_ROOT}/scripts/lib/tls.sh"

NGINX_PORT="${GROUNDCTL_NGINX_PORT:-8080}"
PRIMARY_KEY_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --nginx-port)
            NGINX_PORT="$2"
            shift 2
            ;;
        --primary-key-file)
            PRIMARY_KEY_FILE="$2"
            shift 2
            ;;
        -h|--help)
            grep '^#' "${BASH_SOURCE[0]}" | sed 's/^#//' | sed '1d'
            exit 0
            ;;
        *)
            die "unknown argument: $1 (see --help)"
            ;;
    esac
done

main() {
    require_root
    detect_os

    if [[ -z "${PRIMARY_KEY_FILE}" ]]; then
        die "--primary-key-file is required (path to the primary's ansible-keys/id_ed25519.pub)"
    fi
    [[ -r "${PRIMARY_KEY_FILE}" ]] || die "cannot read --primary-key-file: ${PRIMARY_KEY_FILE}"

    log_info "updating apt package index..."
    apt-get update -qq

    install_sshd_prereqs
    install_nginx

    ensure_relay_sync_user_and_dirs
    authorize_primary_key "$(cat "${PRIMARY_KEY_FILE}")"

    ensure_tls_cert "$(hostname -f 2>/dev/null || hostname)"
    configure_nginx_site "${NGINX_PORT}"

    log_info "relay install complete."
    log_info ""
    log_info "  published repos: https://<this-host>:${NGINX_PORT}/  (systemctl status nginx)"
    log_info "  TLS: self-signed by default (${TLS_CERT_PATH}) — see docs/https.md"
    log_info "  sync user:       groundctl-sync (rsync-over-ssh target, no shell login)"
    log_info "  content root:    /var/lib/groundctl/aptly/public (grows unbounded)"
    log_info ""
    log_info "Now register this relay on the PRIMARY:"
    log_info "  POST /sites"
    log_info "  POST /sites/{id}/relay {\"hostname\": \"<this-host-reachable-name>\", \"ssh_user\": \"groundctl-sync\"}"
    log_info "  PUT  /sites/{id}/environments {\"environment_ids\": [...]}"
    log_info "See docs/relays.md for the full walkthrough."
}

main "$@"
