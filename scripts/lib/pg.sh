#!/usr/bin/env bash
# Postgres provisioning: install, start, idempotent role/db creation.
#
# Every `sudo -u postgres` call below is `--chdir=/tmp` — sudo doesn't
# change directory on its own, so it otherwise inherits install.sh's
# invoking cwd (typically the operator's checkout, e.g.
# ~/groundctl), which the postgres system user has no permission to enter.
# Harmless in practice (pg_isready/psql don't actually need the cwd for
# anything) but printed a "could not change directory ... Permission
# denied" warning on every real install. /tmp is world-readable/enterable
# on any standard Debian/Ubuntu install, so it's always safe here.

install_postgres() {
    log_info "installing postgresql..."
    apt-get install -y postgresql >/dev/null
    systemctl enable --now postgresql >/dev/null

    log_info "waiting for postgresql to accept connections..."
    local tries=0
    until sudo --chdir=/tmp -u postgres pg_isready -q; do
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
    role_exists=$(sudo --chdir=/tmp -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='groundctl'")
    if [[ "${role_exists}" != "1" ]]; then
        log_info "creating postgres role 'groundctl'"
        sudo --chdir=/tmp -u postgres psql -c "CREATE ROLE groundctl WITH LOGIN PASSWORD '${db_password}';" >/dev/null
    else
        log_info "postgres role 'groundctl' already exists — leaving as-is"
    fi

    local db_exists
    db_exists=$(sudo --chdir=/tmp -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='groundctl'")
    if [[ "${db_exists}" != "1" ]]; then
        log_info "creating database 'groundctl'"
        sudo --chdir=/tmp -u postgres psql -c "CREATE DATABASE groundctl OWNER groundctl;" >/dev/null
    else
        log_info "database 'groundctl' already exists — leaving as-is"
    fi
}
