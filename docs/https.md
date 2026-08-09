# HTTPS

## Current state: self-signed by default, everywhere

Both the FastAPI API (uvicorn, port 8000) and the published-repo nginx
(port 8080 by default) terminate TLS. `install.sh`'s `ensure_tls_cert`
(`scripts/lib/tls.sh`) generates a self-signed **ECDSA P-256** cert at
`/etc/groundctl/tls/{cert.pem,key.pem}` on first install if none exists —
idempotent, never regenerated on re-run (matches `ensure_ansible_keypair`'s
precedent). `install-relay.sh` does the same on relay hosts, using the
relay's own hostname as the cert's CN.

**Not ED25519**, despite being otherwise the stronger choice at a given
key size — an earlier version of this script generated ED25519 certs, and
a real browser test (Chrome) failed to negotiate the connection at all
(`ERR_SSL_VERSION_OR_CIPHER_MISMATCH`, not even the normal "connection
isn't private" warning a browser shows for an *untrusted-but-negotiable*
cert). `curl`/OpenSSL on the host itself handled the ED25519 cert fine,
which is what made this easy to miss without an actual browser hitting
the URL. ED25519 TLS certificate support is inconsistent across browsers
and OS TLS stacks in a way P-256 is not — P-256 is supported everywhere
current browsers run. If you already installed with an older version and
hit this, `sudo groundctl-maintain regen-cert` regenerates the cert with
the current key type (backing up the old cert/key first) and restarts
`groundctl` + `nginx` to pick it up — `ensure_tls_cert` itself never
overwrites an existing cert/key pair on its own, so this is the supported
way to force a regeneration without reinstalling.

Plain HTTP on port 80 now only exists as a 301 redirect to HTTPS
(`nginx-groundctl.conf.template`) — there is no unencrypted serving path
left by default.

Why self-signed rather than requiring a real cert up front: Let's Encrypt
needs a real, publicly resolvable domain name and port 80/443 reachability
from the internet, neither of which holds for most lab/test/internal
deployments this app runs in. Self-signed works everywhere with no
external dependency and closes the plaintext-on-the-wire gap immediately;
a CA-issued cert is a documented swap-in below, not a blocker to getting
HTTPS at all. Same posture as `docs/gpg-signing.md`'s off-by-necessity
default with a clear upgrade path.

## How managed hosts come to trust the self-signed cert

Same problem GPG signing has: a managed host can't verify HTTPS traffic to
the primary until it already has something to trust, and it can't safely
fetch that something *over* HTTPS. `bootstrap_client.yml` reads the
primary's CA cert directly off the primary's local filesystem
(`delegate_to: localhost`, `ansible.builtin.slurp`) and pushes it to the
managed host over the same SSH connection used for the rest of bootstrap,
installing it via `update-ca-certificates`. This only runs when
`groundctl_tls_ca_path` is set, which `tasks.py`'s
`_tls_ca_path_if_self_signed()` only does when the configured
`tls_cert_path` actually exists — a host bootstrapped against a primary
using a real CA-issued cert skips this step entirely (the host's existing
system trust store already covers it).

## Swapping in a CA-issued certificate

1. Obtain a cert + key from your CA of choice (certbot/Let's Encrypt,
   internal PKI, etc.) for your real fleet hostname.
2. Replace both files at the paths in `/etc/groundctl/groundctl.env`
   (`TLS_CERT_PATH`/`TLS_KEY_PATH`, default
   `/etc/groundctl/tls/{cert.pem,key.pem}`) — or point those env vars at
   wherever your CA tooling (e.g. certbot) already manages them.
3. `systemctl restart groundctl nginx` (and re-run `configure_nginx_site`
   if you changed the paths themselves, not just the file contents).
4. Already-bootstrapped hosts that installed the old self-signed CA cert
   keep it in their trust store harmlessly (an extra trusted CA that's no
   longer used) — removing it is optional cleanup, not required for the
   new cert to work, since real CA certs are already in every host's
   default trust store.
5. Re-bootstrapping a host after switching to a CA-issued cert correctly
   skips the CA-cert-push step (see above), since `tls_cert_path` no
   longer points at the self-signed file.

Automating certbot's renewal loop is left to your own process supervision
(a systemd timer calling `certbot renew` + a reload hook) — this is
standard certbot usage, not groundctl-specific, so it isn't wired into
`install.sh`.

## Known gaps

- No automated Let's Encrypt/certbot integration — the swap-in above is
  manual.
- `Relay.hostname` has no separate port field (see
  [`docs/limitations.md`](limitations.md)) — `_resolve_published_base_url`
  assumes a relay's nginx is reachable at the bare hostname; a relay
  installed with a non-default `--nginx-port` needs that reflected in the
  `hostname` value itself (e.g. `relay.example.net:8443`) until this gets
  a real port field.
- Self-signed certs are per-host (primary and each relay generate their
  own) — there's no shared CA across a multi-relay fleet, so each relay's
  cert is trusted independently by hosts bootstrapped against it.
