#!/usr/bin/env bash
# groundctl app provisioning: code copy, venv, env file, SSH keypair.

# groundctl.service (API + web UI) listens here — 443 so browsing to the
# fleet hostname needs no port, matching how nginx already defaults to
# HTTPS-everywhere for published repos. Not user-configurable (unlike
# nginx's own port, which shares the host with a fleet's existing web
# services more often): a control-plane UI/API claiming 443 for itself is
# the whole point of this constant, and there's no scenario where an
# operator would want it to silently fall back to a random port instead.
GROUNDCTL_PORT=443

install_app_prereqs() {
    log_info "installing app prerequisites..."
    # libcap2-bin: provides setcap, used by grant_bind_low_ports below to
    # let groundctl.service bind port 443 without running as root.
    apt-get install -y --no-install-recommends \
        python3-venv python3-pip openssh-client libcap2-bin >/dev/null
}

# Node/npm are a BUILD-TIME dependency only (ROADMAP Phase 8's web UI) — the
# deployed artifact is static JS/CSS under app/static, nothing Node-related
# runs as a service. Debian/Ubuntu's own nodejs package is old on some
# releases, but the UI build has no runtime dependency on Node version
# beyond what Vite needs, and this avoids adding NodeSource's own apt repo
# (a second signing-key/trust relationship this project doesn't otherwise
# need) for a build-time-only tool.
install_node_prereqs() {
    log_info "installing node prerequisites..."
    apt-get install -y --no-install-recommends nodejs npm >/dev/null
}

# Builds the React SPA (ui/) and syncs the output into app/static, which
# app/main.py mounts via StaticFiles if present. Idempotent: always rebuilds
# from the checked-out ui/ source, matching sync_app_code's own
# always-overwrite-from-repo posture rather than trying to diff a built
# artifact.
build_ui() {
    log_info "building web UI..."
    ( cd "${REPO_ROOT}/ui" && npm ci --silent && npm run build --silent )
    rm -rf "${REPO_ROOT}/app/static"
    cp -a "${REPO_ROOT}/ui/dist" "${REPO_ROOT}/app/static"
}

install_redis() {
    log_info "installing redis..."
    # Redis is packaged directly in Debian/Ubuntu's own apt repos — no
    # binary-fetch/keyring dance like aptly needed.
    apt-get install -y redis-server >/dev/null
    # Bind loopback only — no auth on Redis in this deployment, same
    # posture as aptly's own unauthenticated API being loopback-scoped.
    sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
    systemctl enable --now redis-server >/dev/null
}

sync_app_code() {
    log_info "copying app code to /opt/groundctl"
    mkdir -p /opt/groundctl
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "${REPO_ROOT}/app/" /opt/groundctl/app/
        # docs/ — served in-app by app/routers/docs.py (GET /api/docs-content),
        # resolved relative to app/'s own location (one level up), same
        # pattern app/main.py uses for app/static. Sibling to app/, not
        # nested inside it, so the checkout's own top-level docs/ layout
        # stays identical in /opt/groundctl.
        rsync -a --delete "${REPO_ROOT}/docs/" /opt/groundctl/docs/
    else
        rm -rf /opt/groundctl/app
        cp -a "${REPO_ROOT}/app" /opt/groundctl/app
        rm -rf /opt/groundctl/docs
        cp -a "${REPO_ROOT}/docs" /opt/groundctl/docs
    fi
    cp "${REPO_ROOT}/requirements.txt" /opt/groundctl/requirements.txt
    cp "${REPO_ROOT}/alembic.ini" /opt/groundctl/alembic.ini
    # Sibling of app/, same as docs/ above — GET /api/version (app/routers/
    # version.py) reads this relative to app/'s own location, since the
    # running process otherwise has no way to know its own version (VERSION
    # previously wasn't deployed at all, only ever read from the checkout
    # by groundctl-maintain itself).
    cp "${REPO_ROOT}/VERSION" /opt/groundctl/VERSION

    # Real bug found live: rsync -a --delete only removes destination
    # files/dirs that are genuinely absent from the SOURCE tree it's
    # mirroring. __pycache__/*.pyc is never present in the source
    # checkout at all (gitignored, generated at runtime in the
    # destination only) — rsync has nothing to compare it against, so it
    # silently leaves old compiled bytecode in place forever, even across
    # a full --delete sync of everything else. A host that had been
    # running long enough to compile app/main.py before this version's
    # /api-prefix change was still SERVING the stale compiled version
    # after a full upgrade — every .py file on disk was current, but the
    # actually-running code wasn't, and nothing about inspecting the
    # checkout or the unit file could reveal it. Clear it explicitly on
    # every sync so Python is always forced to recompile from the
    # .py files that were just written above.
    find /opt/groundctl/app -depth -name "__pycache__" -exec rm -rf {} +

    chown -R groundctl:groundctl /opt/groundctl
}

setup_venv() {
    # --copies: a plain `python3 -m venv` makes bin/python3 a SYMLINK to the
    # system interpreter, not its own binary. grant_bind_low_ports (below)
    # needs a real, independent copy to setcap — capabilities set on a
    # symlink either fail outright or (if the tool follows the link) land
    # on the SYSTEM python3 itself, granting CAP_NET_BIND_SERVICE to every
    # other script on the host that happens to run via that same
    # interpreter. A real copy (~30MB, not meaningfully more disk than the
    # symlink form once site-packages are installed) keeps the capability
    # scoped to groundctl's own venv.
    if [[ ! -x /opt/groundctl/venv/bin/python ]]; then
        log_info "creating python venv"
        sudo -u groundctl python3 -m venv --copies /opt/groundctl/venv
    elif [[ -L /opt/groundctl/venv/bin/python3 ]]; then
        # A venv from before --copies was added above (or from before
        # grant_bind_low_ports existed at all) still has the symlink form.
        # Recreate it rather than leaving a stale venv that would make
        # grant_bind_low_ports setcap the SYSTEM python3 — see above.
        # site-packages get reinstalled immediately below regardless, so
        # nothing here is lost by discarding the old venv.
        log_info "existing venv's python3 is a symlink (pre-dates --copies) — recreating so setcap can target a real binary, not the system interpreter"
        rm -rf /opt/groundctl/venv
        sudo -u groundctl python3 -m venv --copies /opt/groundctl/venv
    fi
    log_info "installing python dependencies..."
    sudo -u groundctl /opt/groundctl/venv/bin/pip install --quiet --upgrade pip
    sudo -u groundctl /opt/groundctl/venv/bin/pip install --quiet -r /opt/groundctl/requirements.txt
}

# groundctl.service runs uvicorn as the unprivileged groundctl user (see
# CLAUDE.md — no service here runs as root) but binds __GROUNDCTL_PORT__
# (443) directly, a privileged port an unprivileged process normally can't
# open. CAP_NET_BIND_SERVICE on the venv's own python3 binary is the
# standard fix for exactly this (same mechanism container runtimes/systemd
# AmbientCapabilities use) — narrower than running the whole process as
# root, and scoped to this one binary, not systemd-wide, so it must be
# re-applied every time setup_venv recreates the venv (a fresh venv has a
# fresh, uncapped binary). Idempotent: setcap unconditionally re-applies,
# cheap either way.
grant_bind_low_ports() {
    log_info "granting CAP_NET_BIND_SERVICE to the venv's python3 (so uvicorn can bind port ${GROUNDCTL_PORT} as user groundctl)"
    setcap 'cap_net_bind_service=+ep' /opt/groundctl/venv/bin/python3
}

# Applies pending Alembic migrations (ROADMAP Phase 7) — run explicitly at
# install/re-install time, ahead of (re)starting groundctl.service, so a
# migration failure surfaces here rather than inside the service's own
# lifespan startup hook (which also runs `alembic upgrade head` as a
# belt-and-suspenders on every boot — see app/main.py). Requires
# groundctl.env to already exist (DATABASE_URL) and the venv to be set up.
run_migrations() {
    log_info "applying database migrations..."
    sudo -u groundctl bash -c '
        set -a
        source /etc/groundctl/groundctl.env
        set +a
        cd /opt/groundctl && exec /opt/groundctl/venv/bin/alembic upgrade head
    '
}

# Bootstraps the very first admin user. POST /auth/register is admin-only
# (real, enforced RBAC — see app/routers/auth.py), so a fresh install has
# no way to create ANY user via the API: there's no admin yet to call it
# with. Without this, the web UI's login screen is unusable after a fresh
# install and the only path was a manual Python one-liner run by hand
# (see docs/quickstart.md's now-secondary "escape hatch" note).
#
# Idempotent like every other step here: if any role=admin user already
# exists, this is a silent no-op — re-running install.sh after a git pull
# must never re-prompt for credentials that are already set.
ensure_first_admin_user() {
    local existing_admin
    existing_admin="$(sudo -u groundctl bash -c '
        set -a
        source /etc/groundctl/groundctl.env
        set +a
        cd /opt/groundctl && exec ./venv/bin/python3 -c "
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User, Role
db = SessionLocal()
user = db.execute(select(User).where(User.role == Role.admin)).scalars().first()
print(user.username if user else \"\")
"
    ' 2>/dev/null)"

    if [[ -n "${existing_admin}" ]]; then
        log_info "admin user '${existing_admin}' already exists — skipping"
        return
    fi

    ADMIN_USERNAME="${GROUNDCTL_ADMIN_USERNAME:-}"
    ADMIN_EMAIL="${GROUNDCTL_ADMIN_EMAIL:-}"
    ADMIN_PASSWORD="${GROUNDCTL_ADMIN_PASSWORD:-}"

    prompt_if_unset ADMIN_USERNAME "Admin username" "admin"
    prompt_if_unset ADMIN_EMAIL "Admin email" "admin@${FLEET_HOSTNAME}"

    local generated_password=0
    if [[ -z "${ADMIN_PASSWORD}" ]]; then
        if [[ -t 0 ]]; then
            local pw1 pw2
            while true; do
                read -r -s -p "Admin password (min 8 chars): " pw1; echo
                read -r -s -p "Confirm password: " pw2; echo
                if [[ "${pw1}" != "${pw2}" ]]; then
                    log_warn "passwords did not match — try again"
                elif [[ "${#pw1}" -lt 8 ]]; then
                    log_warn "password must be at least 8 characters — try again"
                else
                    ADMIN_PASSWORD="${pw1}"
                    break
                fi
            done
        else
            # Non-interactive (piped/cron/CI) with no password supplied —
            # never hang on read, never fall back to a weak default.
            # openssl is already a hard dependency (install_base_prereqs,
            # ensure_tls_cert) so this needs no new tool.
            ADMIN_PASSWORD="$(openssl rand -base64 18)"
            generated_password=1
        fi
    fi

    log_info "creating first admin user '${ADMIN_USERNAME}'..."
    # Credentials passed via sys.argv (positional), never string-
    # interpolated into the embedded Python source — a password
    # containing quotes/backticks/$ must not be able to break out of the
    # script, same injection-safety posture as the RELEASE_NOTES fix in
    # .github/workflows/release.yml.
    sudo -u groundctl bash -c '
        set -a
        source /etc/groundctl/groundctl.env
        set +a
        cd /opt/groundctl && exec ./venv/bin/python3 -c "
import sys
from app.database import SessionLocal
from app.models import User, Role
from app.auth import hash_password
db = SessionLocal()
db.add(User(username=sys.argv[1], email=sys.argv[2],
            hashed_password=hash_password(sys.argv[3]), role=Role.admin))
db.commit()
" "$1" "$2" "$3"
    ' _ "${ADMIN_USERNAME}" "${ADMIN_EMAIL}" "${ADMIN_PASSWORD}"

    ADMIN_USER_CREATED=1
    if [[ "${generated_password}" -eq 1 ]]; then
        ADMIN_PASSWORD_WAS_GENERATED=1
        # ADMIN_PASSWORD deliberately left set (this shell's memory only)
        # so main()'s final summary can print it exactly once — never
        # written to a file, never passed to log_info (which lands in
        # journald), only echoed directly to the terminal at the very end.
    fi
}

# Reads an existing key from groundctl.env if the file already exists, else
# generates a fresh random value. Never regenerates an existing secret —
# doing so on re-run would desync the app from an already-provisioned
# Postgres role or invalidate every already-issued JWT.
_read_or_generate() {
    local key="$1"
    local env_file="/etc/groundctl/groundctl.env"
    if [[ -f "${env_file}" ]]; then
        local existing
        existing="$(grep -E "^${key}=" "${env_file}" 2>/dev/null | head -1 | cut -d= -f2-)"
        if [[ -n "${existing}" ]]; then
            echo "${existing}"
            return
        fi
    fi
    openssl rand -hex 24
}

ensure_ansible_keypair() {
    local key_dir="/etc/groundctl/ansible-keys"
    mkdir -p "${key_dir}"
    # Ownership must be fixed BEFORE ssh-keygen runs as the groundctl user
    # below — mkdir -p above creates the directory as root (this whole
    # script runs as root), and `sudo -u groundctl ssh-keygen -f
    # ${key_dir}/id_ed25519` fails with "Permission denied" writing into a
    # directory groundctl doesn't yet own. A real bug found on a fresh
    # install: the chown used to run after ssh-keygen, which only worked
    # by accident on a re-run once the directory already existed with the
    # right owner from wherever it first got created correctly.
    chown -R groundctl:groundctl "${key_dir}"
    chmod 700 "${key_dir}"
    if [[ ! -f "${key_dir}/id_ed25519" ]]; then
        log_info "generating ansible SSH keypair"
        sudo -u groundctl ssh-keygen -t ed25519 -f "${key_dir}/id_ed25519" -N "" -q
    else
        log_info "ansible SSH keypair already exists — leaving as-is"
    fi
    chown groundctl:groundctl "${key_dir}/id_ed25519" "${key_dir}/id_ed25519.pub"
    chmod 600 "${key_dir}/id_ed25519"
    chmod 644 "${key_dir}/id_ed25519.pub"
}

write_groundctl_env() {
    local fleet_hostname="$1"
    local nginx_port="$2"
    local env_file="/etc/groundctl/groundctl.env"

    local pg_password jwt_secret
    pg_password="$(_read_or_generate POSTGRES_PASSWORD)"
    jwt_secret="$(_read_or_generate JWT_SECRET)"

    local old_hash=""
    [[ -f "${env_file}" ]] && old_hash="$(md5sum "${env_file}" | cut -d' ' -f1)"

    log_info "writing /etc/groundctl/groundctl.env"
    umask 077
    cat > "${env_file}" <<EOF
POSTGRES_PASSWORD=${pg_password}
DATABASE_URL=postgresql+psycopg://groundctl:${pg_password}@127.0.0.1:5432/groundctl
APTLY_API_URL=http://127.0.0.1:8090
PUBLISHED_REPO_BASE_URL=https://${fleet_hostname}:${nginx_port}
GROUNDCTL_API_BASE_URL=https://${fleet_hostname}
JWT_SECRET=${jwt_secret}
ANSIBLE_PRIVATE_KEY_PATH=/etc/groundctl/ansible-keys/id_ed25519
ANSIBLE_HOST_KEYS_DIR=/etc/groundctl/ansible-keys/hosts
TLS_CERT_PATH=${TLS_CERT_PATH}
TLS_KEY_PATH=${TLS_KEY_PATH}
REDIS_URL=redis://127.0.0.1:6379/0
EOF
    # Belt-and-suspenders on top of umask 077 above — this file holds the
    # Postgres password and JWT signing secret in plaintext (see
    # docs/secrets.md for the documented sops/age-encryption opt-in).
    # Re-asserted on every write, not just at creation, in case a prior
    # version of this script or a manual edit left it more permissive.
    chown root:groundctl "${env_file}"
    chmod 640 "${env_file}"

    local new_hash
    new_hash="$(md5sum "${env_file}" | cut -d' ' -f1)"
    if [[ "${old_hash}" != "${new_hash}" ]]; then
        ENV_FILE_CHANGED=1
    else
        ENV_FILE_CHANGED=0
    fi

    # ensure_postgres_role_and_db needs the password too — export for caller.
    GENERATED_PG_PASSWORD="${pg_password}"

    write_maintain_conf
}

# Install-tooling-only metadata for groundctl-maintain (scripts/groundctl-maintain.sh)
# — deliberately separate from groundctl.env above, which is the
# application's own runtime config, sourced by the app process itself.
# Records the git checkout install.sh was run from, so `groundctl-maintain
# upgrade` (run later as a standalone command, possibly from a different
# working directory or even a different shell session entirely) knows
# where to git fetch/checkout into.
write_maintain_conf() {
    local conf_file="/etc/groundctl/maintain.conf"
    log_info "writing ${conf_file}"
    umask 077
    cat > "${conf_file}" <<EOF
GROUNDCTL_REPO_ROOT=${REPO_ROOT}
EOF
    chown root:root "${conf_file}"
    chmod 600 "${conf_file}"
}

# Shared by groundctl.service, groundctl-worker.service, groundctl-beat.service
# — same install/restart-if-changed pattern for all three app-code units.
# Renders the template into a temp file first (sed substitution, currently
# only meaningful for groundctl.service's TLS paths and port — a no-op
# passthrough for units with no __PLACEHOLDER__ tokens) so change-detection
# compares actual rendered content, not the raw template against a
# substituted file.
_install_app_service() {
    local unit_name="$1"
    local rendered
    rendered="$(mktemp)"
    sed -e "s#__TLS_CERT_PATH__#${TLS_CERT_PATH}#" \
        -e "s#__TLS_KEY_PATH__#${TLS_KEY_PATH}#" \
        -e "s#__GROUNDCTL_PORT__#${GROUNDCTL_PORT}#" \
        "${REPO_ROOT}/systemd/${unit_name}.service.template" > "${rendered}"

    local unit_changed=1
    if [[ -f "/etc/systemd/system/${unit_name}.service" ]] && \
       cmp -s "${rendered}" "/etc/systemd/system/${unit_name}.service"; then
        unit_changed=0
    fi

    install -m 0644 "${rendered}" "/etc/systemd/system/${unit_name}.service"
    rm -f "${rendered}"
    systemctl daemon-reload
    systemctl enable "${unit_name}" >/dev/null

    if [[ "${unit_changed}" -eq 1 ]] || [[ "${ENV_FILE_CHANGED:-0}" -eq 1 ]] || ! systemctl is-active --quiet "${unit_name}"; then
        systemctl restart "${unit_name}"
    else
        log_info "${unit_name}.service unit/env unchanged and already running — leaving it up"
    fi
}

install_groundctl_service() {
    _install_app_service "groundctl"
}

install_groundctl_worker_service() {
    _install_app_service "groundctl-worker"
}

install_groundctl_beat_service() {
    _install_app_service "groundctl-beat"
}

# Installs scripts/groundctl-maintain.sh to /usr/local/bin — a standalone
# command (NOT a wrapper around install.sh, see the script's own header)
# for post-install operations, `upgrade` today. Same install pattern
# scripts/lib/aptly.sh uses for the aptly binary itself. Re-run on every
# install.sh invocation (and by `groundctl-maintain upgrade` itself, at
# the end of its own run) so the installed copy never drifts from the
# checkout's source.
install_maintain_script() {
    log_info "installing groundctl-maintain to /usr/local/bin"
    install -m 0755 "${REPO_ROOT}/scripts/groundctl-maintain.sh" /usr/local/bin/groundctl-maintain
}
