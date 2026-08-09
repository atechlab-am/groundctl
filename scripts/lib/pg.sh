#!/usr/bin/env bash
# Postgres provisioning: install, start, idempotent role/db creation.

install_postgres() {
    log_info "installing postgresql..."
    apt-get install -y postgresql >/dev/null
    systemctl enable --now postgresql >/dev/null

    log_info "waiting for postgresql to accept connections..."
    local tries=0
    until sudo -u postgres pg_isready -q; do
        tries=$((tries + 1))
        [[ "${tries}" -ge 30 ]] && die "postgresql did not become ready in time"
        sleep 1
    done
}

# Idempotently ensure the groundctl role and database exist. Never drops or
# recreates — password is generated once by the caller and passed in; if the
# role already exists we do NOT touch its password (it may differ from what's
# in groundctl.env only if an admin manually changed it out-of-band, which is
# their call, not ours to silently overwrite).
ensure_postgres_role_and_db() {
    local db_password="$1"

    local role_exists
    role_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='groundctl'")
    if [[ "${role_exists}" != "1" ]]; then
        log_info "creating postgres role 'groundctl'"
        sudo -u postgres psql -c "CREATE ROLE groundctl WITH LOGIN PASSWORD '${db_password}';" >/dev/null
    else
        log_info "postgres role 'groundctl' already exists — leaving as-is"
    fi

    local db_exists
    db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='groundctl'")
    if [[ "${db_exists}" != "1" ]]; then
        log_info "creating database 'groundctl'"
        sudo -u postgres psql -c "CREATE DATABASE groundctl OWNER groundctl;" >/dev/null
    else
        log_info "database 'groundctl' already exists — leaving as-is"
    fi
}
