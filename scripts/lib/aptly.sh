#!/usr/bin/env bash
# aptly provisioning: OS packages, keyrings, binary, config, service.

APTLY_VERSION="1.6.3"
UBUNTU_KEYRING_DEB_VERSION="2023.11.28.1"

install_aptly_prereqs() {
    log_info "installing aptly prerequisites..."
    apt-get install -y --no-install-recommends \
        ca-certificates curl unzip gnupg debian-archive-keyring \
        bzip2 gzip xz-utils >/dev/null

    if [[ "${OS_ID}" == "ubuntu" ]]; then
        apt-get install -y ubuntu-keyring >/dev/null
    else
        install_ubuntu_keyring_on_debian
    fi
}

# ubuntu-keyring isn't packaged for Debian — fetch it directly so aptly can
# verify Release-file signatures on Ubuntu archive mirrors from a Debian
# control-plane host too.
install_ubuntu_keyring_on_debian() {
    if [[ -f /usr/share/keyrings/ubuntu-archive-keyring.gpg ]]; then
        log_info "ubuntu-archive-keyring already present — skipping fetch"
        return
    fi
    log_info "fetching ubuntu-keyring package (Debian host, not apt-installable)..."
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSL -o "${tmp}/ubuntu-keyring.deb" \
        "http://archive.ubuntu.com/ubuntu/pool/main/u/ubuntu-keyring/ubuntu-keyring_${UBUNTU_KEYRING_DEB_VERSION}_all.deb"
    dpkg -x "${tmp}/ubuntu-keyring.deb" "${tmp}/extracted"
    cp "${tmp}/extracted/usr/share/keyrings/"*.gpg /usr/share/keyrings/
    rm -rf "${tmp}"
}

install_aptly_binary() {
    local arch
    arch="$(aptly_arch)"

    if [[ -x /usr/local/bin/aptly ]]; then
        local current_version
        current_version="$(/usr/local/bin/aptly version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        if [[ "${current_version}" == "${APTLY_VERSION}" ]]; then
            log_info "aptly ${APTLY_VERSION} already installed — skipping download"
            return
        fi
        log_info "aptly version mismatch (have ${current_version:-none}, want ${APTLY_VERSION}) — reinstalling"
    fi

    log_info "downloading aptly ${APTLY_VERSION} (${arch})..."
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSL -o "${tmp}/aptly.zip" \
        "https://github.com/aptly-dev/aptly/releases/download/v${APTLY_VERSION}/aptly_${APTLY_VERSION}_linux_${arch}.zip"
    unzip -q "${tmp}/aptly.zip" -d "${tmp}/extracted"
    install -m 0755 "${tmp}/extracted/aptly_${APTLY_VERSION}_linux_${arch}/aptly" /usr/local/bin/aptly
    rm -rf "${tmp}"
}

ensure_aptly_user_and_dirs() {
    if ! id groundctl >/dev/null 2>&1; then
        log_info "creating system user 'groundctl'"
        useradd --system --home-dir /var/lib/groundctl --shell /usr/sbin/nologin --create-home groundctl
    fi

    mkdir -p /var/lib/groundctl/aptly/public
    mkdir -p /etc/groundctl
    chown -R groundctl:groundctl /var/lib/groundctl
}

write_aptly_conf() {
    log_info "writing /etc/groundctl/aptly.conf"
    install -m 0644 -o root -g groundctl \
        "${REPO_ROOT}/systemd/aptly.conf.template" /etc/groundctl/aptly.conf
}

# aptly shells out to gpgv, which verifies exclusively against
# ~/.gnupg/trustedkeys.gpg for the invoking user — NOT the default pubring,
# and NOT whatever was passed to the mirror-create API call (that only
# affects that one call). This step is silent-failure-prone if skipped:
# mirror syncs fail with a confusing "no public key" gpgv error. Never make
# this conditional/optional.
import_aptly_trustedkeys() {
    log_info "importing archive keyrings into groundctl's trustedkeys.gpg"
    local gnupg_dir="/var/lib/groundctl/.gnupg"
    sudo -u groundctl mkdir -p "${gnupg_dir}"
    chmod 700 "${gnupg_dir}"

    local keyring
    for keyring in /usr/share/keyrings/debian-archive-keyring.gpg /usr/share/keyrings/ubuntu-archive-keyring.gpg; do
        [[ -f "${keyring}" ]] || { log_warn "keyring not found: ${keyring} — skipping"; continue; }
        sudo -u groundctl bash -c \
            "gpg --no-default-keyring --keyring '${keyring}' --export | gpg --no-default-keyring --keyring '${gnupg_dir}/trustedkeys.gpg' --import" \
            >/dev/null 2>&1
    done
}

install_aptly_service() {
    install -m 0644 "${REPO_ROOT}/systemd/aptly.service.template" /etc/systemd/system/aptly.service
    systemctl daemon-reload
    systemctl enable aptly >/dev/null
    if systemctl is-active --quiet aptly; then
        log_info "aptly.service already running — leaving it up (no unnecessary restart)"
    else
        systemctl start aptly
    fi
}
