#!/usr/bin/env bash
# TLS cert provisioning — self-signed by default so the API and published
# repos aren't plaintext-on-the-wire out of the box, with a documented
# swap-in for a real CA-issued cert in production (see docs/https.md).

TLS_CERT_PATH="/etc/groundctl/tls/cert.pem"
TLS_KEY_PATH="/etc/groundctl/tls/key.pem"

ensure_tls_cert() {
    local fleet_hostname="$1"
    local cert_dir
    cert_dir="$(dirname "${TLS_CERT_PATH}")"

    if [[ -f "${TLS_CERT_PATH}" && -f "${TLS_KEY_PATH}" ]]; then
        log_info "TLS cert already exists at ${TLS_CERT_PATH} — leaving as-is"
        log_info "(to switch to a CA-issued cert, replace both files and restart" \
                 "groundctl + nginx — see docs/https.md)"
        return
    fi

    log_info "generating self-signed TLS cert for ${fleet_hostname}"
    mkdir -p "${cert_dir}"
    openssl req -x509 -newkey ed25519 -days 825 -nodes \
        -keyout "${TLS_KEY_PATH}" -out "${TLS_CERT_PATH}" \
        -subj "/CN=${fleet_hostname}" \
        -addext "subjectAltName=DNS:${fleet_hostname}" \
        2>/dev/null

    # The cert (public, world-readable is fine) uses 644. The private key
    # is more delicate: nginx's master process reads it as root before
    # dropping privileges (any permission works for nginx), but on the
    # PRIMARY the groundctl app also reads it directly for uvicorn's
    # --ssl-keyfile, running as the unprivileged `groundctl` user — so the
    # key needs group-readable there. This lib is shared with
    # install-relay.sh, where no `groundctl` group exists at all, so only
    # chgrp to it when present; the key stays root-only (600) on a relay,
    # which is correct since nothing but nginx-as-root reads it there.
    chown root:root "${TLS_CERT_PATH}"
    chmod 644 "${TLS_CERT_PATH}"
    chown root:root "${TLS_KEY_PATH}"
    chmod 600 "${TLS_KEY_PATH}"
    if getent group groundctl >/dev/null 2>&1; then
        chgrp groundctl "${TLS_KEY_PATH}"
        chmod 640 "${TLS_KEY_PATH}"
    fi
}
