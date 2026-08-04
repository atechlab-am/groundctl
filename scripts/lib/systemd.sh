#!/usr/bin/env bash
# nginx provisioning (grouped here as the remaining system-service concern).

install_nginx() {
    log_info "installing nginx..."
    apt-get install -y nginx >/dev/null
}

configure_nginx_site() {
    local nginx_port="$1"

    log_info "writing nginx site config (port ${nginx_port})"
    sed -e "s/__NGINX_PORT__/${nginx_port}/" \
        -e "s#__TLS_CERT_PATH__#${TLS_CERT_PATH}#" \
        -e "s#__TLS_KEY_PATH__#${TLS_KEY_PATH}#" \
        "${REPO_ROOT}/systemd/nginx-groundctl.conf.template" \
        > /etc/nginx/sites-available/groundctl.conf

    ln -sf /etc/nginx/sites-available/groundctl.conf /etc/nginx/sites-enabled/groundctl.conf

    # The default site also binds port 80 by default and would conflict.
    if [[ -e /etc/nginx/sites-enabled/default ]]; then
        log_info "disabling nginx default site (conflicts on port 80)"
        rm -f /etc/nginx/sites-enabled/default
    fi

    nginx -t
    systemctl enable nginx >/dev/null
    systemctl reload-or-restart nginx
}
