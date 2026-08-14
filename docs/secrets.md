# Secrets

## Current state: plaintext file, restrictive permissions

`install.sh` writes every runtime secret (Postgres password, JWT signing
secret) into `/etc/groundctl/groundctl.env`, plaintext, `640 root:groundctl`
(only root and members of the `groundctl` group can read it — the app
itself runs as `groundctl`). `write_groundctl_env` re-asserts this
ownership/mode on every run, not just at first creation, and never
regenerates an existing secret (a re-run would desync the Postgres role
password or invalidate every already-issued JWT).

There is no integration with an external secrets manager (Vault, sops,
cloud KMS, etc.) — `app/config.py` reads `.env`/environment variables via
`pydantic-settings`, same as any other file-based config.

This is a real gap for anyone running groundctl where "root can read a file
on this box" isn't an acceptable trust boundary — e.g. multiple
administrators with different trust levels, or compliance requirements for
encryption-at-rest on credential material. It is not a gap for a
single-operator or small-team deployment where root-on-the-control-plane
already implies full trust.

## Documented opt-in: encrypt `groundctl.env` at rest with sops + age

[sops](https://github.com/getsops/sops) is designed specifically to wrap
existing plaintext-env-var workflows without requiring an app-code
rewrite — it encrypts values in place and decrypts them back out at
deploy time, so `config.py`'s existing `env_file=".env"` loading needs no
changes.

1. Install `sops` and generate an [age](https://github.com/FiloSottile/age)
   keypair on a machine you trust (not necessarily the groundctl host
   itself):
   ```
   age-keygen -o groundctl-secrets.age.key
   ```
2. After `install.sh` has generated `/etc/groundctl/groundctl.env` once,
   encrypt it:
   ```
   sops --age <public-key-from-step-1> -e /etc/groundctl/groundctl.env \
     > /etc/groundctl/groundctl.env.enc
   ```
   Store `groundctl.env.enc` in your config-management/secrets repo instead
   of the plaintext file; keep the age private key off the groundctl host
   except when decrypting.
3. On deploy/re-provision, decrypt back into place before `install.sh`
   writes/restarts services:
   ```
   sops --age-key-file groundctl-secrets.age.key -d groundctl.env.enc \
     > /etc/groundctl/groundctl.env
   ```

This is genuinely encryption-at-rest for the file as it sits in your
config-management system or backups — it does **not** change how the
running `groundctl`/`groundctl-worker`/`groundctl-beat` processes read
secrets (still plaintext env vars in the process's own memory, same as any
12-factor app) and does **not** integrate sops into `install.sh` itself.
Wiring an automated decrypt-on-deploy step is left to whatever
config-management tooling you already use to invoke `install.sh`.

## What's out of scope here

A full external secrets-manager integration (HashiCorp Vault, cloud KMS
with dynamic credential leasing, automatic rotation) is a materially
larger operational dependency than this project takes on anywhere else —
there's no precedent for a secrets-manager server in `docker-compose.yml`
or the systemd units, and adding one changes the deployment model for
every operator, not just those who want it. The sops/age approach above
was chosen instead because it's opt-in, requires no new always-on service,
and wraps the existing file-based config rather than replacing it.

## Other secret-handling notes

- The Ansible SSH private key(s) — the shared fleet key at
  `ansible_private_key_path` and, since this phase, per-host keys under
  `ansible_host_keys_dir` (see [`docs/limitations.md`](limitations.md)) —
  live on the primary's filesystem only, never in Postgres or in an API
  response.
- `Job.log_output` stores raw Ansible output. `no_log: true` is required on
  any playbook task that handles credential material — the existing
  playbooks (bootstrap, apply-updates, gather-facts, run-command,
  manage-package, sync-relay) pass no secrets through `extra_vars` today.
- The TLS private key (`tls_key_path`) is `600 root:root` on relays and
  `640 root:groundctl` on the primary — see `scripts/lib/tls.sh`.
