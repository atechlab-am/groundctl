#!/usr/bin/env bash
# Relay-specific provisioning. A relay never runs aptly — it only receives
# an already-published tree via rsync and serves it with nginx (see
# app/ansible/playbooks/sync_relay.yml and docs/relays.md). No Postgres, no
# FastAPI app, no Celery worker/beat, no JWT secret — genuinely thin.

# Unprivileged system user the primary's rsync-over-SSH connection lands as.
# No rsync daemon: `rsync -e ssh` is sufficient and avoids running a second
# listening service with its own auth model — sshd + a writable directory
# is the whole surface.
ensure_relay_sync_user_and_dirs() {
    if ! id groundctl-sync >/dev/null 2>&1; then
        log_info "creating system user 'groundctl-sync'"
        useradd --system --home-dir /var/lib/groundctl --shell /usr/sbin/nologin --create-home groundctl-sync
    fi

    mkdir -p /var/lib/groundctl/aptly/public
    chown -R groundctl-sync:groundctl-sync /var/lib/groundctl
}

# Authorizes the PRIMARY's ansible public key for the sync user, so the
# primary's shared fleet key (already trusted for every managed host) also
# works for the rsync-over-SSH hop and for ProxyJump routing through this
# relay to hosts behind it. Takes the primary's id_ed25519.pub CONTENTS as
# an argument (operator copies it in — see docs/relays.md; there's no
# automated key-exchange mechanism between primary and relay in this phase).
authorize_primary_key() {
    local pubkey_content="$1"
    local ssh_dir="/var/lib/groundctl/.ssh"

    mkdir -p "${ssh_dir}"
    chmod 700 "${ssh_dir}"
    if ! grep -qF "${pubkey_content}" "${ssh_dir}/authorized_keys" 2>/dev/null; then
        log_info "authorizing primary's ansible key for groundctl-sync"
        echo "${pubkey_content}" >> "${ssh_dir}/authorized_keys"
    else
        log_info "primary's ansible key already authorized — skipping"
    fi
    chmod 600 "${ssh_dir}/authorized_keys"
    chown -R groundctl-sync:groundctl-sync "${ssh_dir}"
}

install_sshd_prereqs() {
    log_info "installing sshd..."
    apt-get install -y --no-install-recommends openssh-server >/dev/null
    systemctl enable ssh >/dev/null
    systemctl start ssh
}
