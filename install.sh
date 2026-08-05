#!/usr/bin/env bash
#
# Native installer for groundctl — provisions Postgres, aptly, nginx, and the
# groundctl FastAPI app as systemd services directly on a Debian/Ubuntu host.
# Satellite-style: one script, idempotent, safe to re-run for config changes
# or upgrades.
#
# ASSUMPTION: must be run from inside a checked-out copy of this repo
# (./install.sh from repo root). It does not clone the repo itself — there
# is no published release/package registry for groundctl yet.
#
# Usage:
#   sudo ./install.sh [--fleet-hostname HOST] [--nginx-port PORT]
#
# Or via environment variables:
#   GROUNDCTL_FLEET_HOSTNAME=repo.example.com GROUNDCTL_NGINX_PORT=8080 sudo -E ./install.sh
#
# See install.env.example and docs/install.md for details.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/lib/os.sh
. "${REPO_ROOT}/scripts/lib/os.sh"
# shellcheck source=scripts/lib/pg.sh
. "${REPO_ROOT}/scripts/lib/pg.sh"
# shellcheck source=scripts/lib/aptly.sh
. "${REPO_ROOT}/scripts/lib/aptly.sh"
# shellcheck source=scripts/lib/app.sh
. "${REPO_ROOT}/scripts/lib/app.sh"
# shellcheck source=scripts/lib/systemd.sh
. "${REPO_ROOT}/scripts/lib/systemd.sh"
# shellcheck source=scripts/lib/tls.sh
. "${REPO_ROOT}/scripts/lib/tls.sh"

# Empty (not defaulted here) so prompt_if_unset (scripts/lib/os.sh) can
# tell "flag/env supplied" apart from "prompt for it, falling back to the
# placeholder default if unattended." Flags parsed below and the
# GROUNDCTL_* env vars both still fully bypass the prompt, unchanged.
FLEET_HOSTNAME="${GROUNDCTL_FLEET_HOSTNAME:-}"
NGINX_PORT="${GROUNDCTL_NGINX_PORT:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fleet-hostname)
            FLEET_HOSTNAME="$2"
            shift 2
            ;;
        --nginx-port)
            NGINX_PORT="$2"
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

    prompt_if_unset FLEET_HOSTNAME \
        "Fleet hostname (address managed hosts will reach this server at)" \
        "groundctl.local"
    prompt_if_unset NGINX_PORT "nginx published-repo port" "8080"

    if [[ "${FLEET_HOSTNAME}" == "groundctl.local" ]]; then
        log_warn "using placeholder fleet hostname 'groundctl.local' — pass --fleet-hostname" \
                 "or set GROUNDCTL_FLEET_HOSTNAME to the address your managed hosts will use" \
                 "to reach this server. Fix this in /etc/groundctl/groundctl.env if needed."
    fi

    log_info "updating apt package index..."
    apt-get update -qq

    install_base_prereqs
    install_postgres
    install_redis
    install_aptly_prereqs
    install_app_prereqs
    install_node_prereqs
    install_nginx

    ensure_aptly_user_and_dirs
    install_aptly_binary
    import_aptly_trustedkeys
    write_aptly_conf
    install_aptly_service

    build_ui
    sync_app_code
    setup_venv
    grant_bind_low_ports
    ensure_ansible_keypair
    ensure_tls_cert "${FLEET_HOSTNAME}"
    write_groundctl_env "${FLEET_HOSTNAME}" "${NGINX_PORT}"
    ensure_postgres_role_and_db "${GENERATED_PG_PASSWORD}"
    run_migrations
    ensure_first_admin_user
    install_groundctl_service
    install_groundctl_worker_service
    install_groundctl_beat_service
    install_maintain_script

    configure_nginx_site "${NGINX_PORT}"

    log_info "install complete."
    log_info ""
    log_info "  groundctl API + web UI: https://<this-host>  (systemctl status groundctl)"
    log_info "  published repos: https://${FLEET_HOSTNAME}:${NGINX_PORT}/  (systemctl status nginx)"
    log_info "  TLS: self-signed by default (${TLS_CERT_PATH}) — see docs/https.md" \
             "for swapping in a CA-issued cert"
    log_info "  aptly (internal, loopback only): 127.0.0.1:8090"
    log_info "  job worker:      systemctl status groundctl-worker"
    log_info "  scheduler:       systemctl status groundctl-beat"
    log_info ""
    log_info "  config:  /etc/groundctl/groundctl.env"
    log_info "  ssh key: /etc/groundctl/ansible-keys/id_ed25519.pub"
    log_info "           (authorize this public key on every host you plan to manage)"
    log_info ""
    log_info "  aptly data root (grows unbounded — put it on a volume with headroom):"
    log_info "    /var/lib/groundctl/aptly"
    log_info ""
    log_info "  to upgrade later: sudo groundctl-maintain upgrade"
    log_info ""
    if [[ "${ADMIN_USER_CREATED:-0}" -eq 1 ]]; then
        log_info "  first admin user: ${ADMIN_USERNAME}"
        if [[ "${ADMIN_PASSWORD_WAS_GENERATED:-0}" -eq 1 ]]; then
            log_info "  generated password: ${ADMIN_PASSWORD}"
            log_info "  (shown once — save it now; it is not stored anywhere and cannot be recovered)"
        fi
        log_info "  log in at https://<this-host>"
        log_info ""
    fi
    if [[ "${FLEET_HOSTNAME}" == "groundctl.local" ]]; then
        log_warn "PUBLISHED_REPO_BASE_URL is still the placeholder 'groundctl.local' —" \
                 "edit /etc/groundctl/groundctl.env and 'systemctl restart groundctl' before" \
                 "onboarding real managed hosts."
    fi
    log_info "See docs/quickstart.md for the API walkthrough (register/login/mirror/promote)."
}

main "$@"
