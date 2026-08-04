#!/usr/bin/env bash
# OS/root checks and shared logging helpers.

log_info()  { echo "[groundctl-install] $*"; }
log_warn()  { echo "[groundctl-install] WARNING: $*" >&2; }
log_error() { echo "[groundctl-install] ERROR: $*" >&2; }
die()       { log_error "$*"; exit 1; }

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "must be run as root (try: sudo ./install.sh)"
    fi
}

install_base_prereqs() {
    log_info "installing base prerequisites..."
    apt-get install -y --no-install-recommends openssl >/dev/null
}

detect_os() {
    [[ -r /etc/os-release ]] || die "cannot find /etc/os-release — unsupported OS"
    # shellcheck source=/dev/null
    . /etc/os-release
    case "${ID:-}" in
        debian|ubuntu) ;;
        *) die "unsupported OS '${ID:-unknown}' — groundctl installs on Debian or Ubuntu only" ;;
    esac
    OS_ID="${ID}"
    OS_CODENAME="${VERSION_CODENAME:-}"
    log_info "detected OS: ${OS_ID} (${OS_CODENAME})"
}

# Prints the on-disk architecture string aptly's release assets use.
aptly_arch() {
    case "$(dpkg --print-architecture)" in
        amd64) echo "amd64" ;;
        arm64) echo "arm64" ;;
        armhf) echo "arm" ;;
        *) die "unsupported architecture: $(dpkg --print-architecture)" ;;
    esac
}
