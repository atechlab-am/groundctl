#!/usr/bin/env bash
# TLS cert provisioning — self-signed by default so the API and published
# repos aren't plaintext-on-the-wire out of the box, with a documented
# swap-in for a real CA-issued cert in production (see docs/https.md).

TLS_CERT_PATH="/etc/groundctl/tls/cert.pem"
TLS_KEY_PATH="/etc/groundctl/tls/key.pem"

ensure_tls_cert() {
    local fleet_hostname="$1"

    if [[ -f "${TLS_CERT_PATH}" && -f "${TLS_KEY_PATH}" ]]; then
        log_info "TLS cert already exists at ${TLS_CERT_PATH} — leaving as-is"
        log_info "(to switch to a CA-issued cert, replace both files and restart" \
                 "groundctl + nginx — see docs/https.md; to regenerate a" \
                 "self-signed cert, see 'groundctl-maintain regen-cert')"
        return
    fi

    _generate_tls_cert "${fleet_hostname}"
}

# Unconditional — no existence check. Called by ensure_tls_cert above
# (only reached once no cert exists yet) and by groundctl-maintain's
# regen-cert subcommand (explicit, operator-requested overwrite of an
# existing cert — e.g. switching key type, or the fleet hostname changed).
_generate_tls_cert() {
    local fleet_hostname="$1"
    local cert_dir
    cert_dir="$(dirname "${TLS_CERT_PATH}")"

    log_info "generating self-signed TLS cert for ${fleet_hostname}"
    mkdir -p "${cert_dir}"
    # ECDSA P-256, not ed25519: found live that Chrome fails ED25519 cert
    # negotiation outright (ERR_SSL_VERSION_OR_CIPHER_MISMATCH, not even
    # the normal "not private" warning a browser shows for an untrusted
    # cert it can otherwise negotiate) — ED25519 TLS certificate support
    # is inconsistent across browsers/OS TLS stacks in a way P-256 is not;
    # curl/OpenSSL on the host itself negotiated the ED25519 cert fine,
    # which is what made this easy to miss without an actual browser test.
    # P-256 is supported everywhere and still meaningfully stronger than
    # RSA for a self-signed cert at this key size.
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -days 825 -nodes \
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
