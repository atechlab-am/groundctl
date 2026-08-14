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

# Prompts for a value with a default shown in brackets, but ONLY if the
# variable wasn't already set via flag or env var — flags/env always win
# silently, no prompt, so scripted/non-interactive runs never block on
# stdin. Skips prompting entirely if stdin isn't a TTY (piped input,
# cron, CI) — falls through to the default in that case rather than
# hanging.
prompt_if_unset() {
    local varname="$1" prompt_text="$2" default_value="$3"
    local current="${!varname}"
    if [[ -n "${current}" ]]; then
        return  # already set via flag/env — don't prompt
    fi
    if [[ ! -t 0 ]]; then
        printf -v "${varname}" '%s' "${default_value}"
        return
    fi
    local input
    read -r -p "${prompt_text} [${default_value}]: " input
    printf -v "${varname}" '%s' "${input:-${default_value}}"
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
