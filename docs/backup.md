# Backup and restore

Groundctl has two stateful stores:

- **Postgres** (`groundctl` database) — every control-plane record:
  users, repositories, content views/versions, environments, servers,
  jobs, audit log, everything.
- **`/var/lib/groundctl`** — aptly's data root (mirror/snapshot/published-
  package pool) plus the local GPG keyring used for signing (see
  [`docs/gpg-signing.md`](gpg-signing.md)). This is the only place
  aptly's actual package content lives.

Both need to be backed up together — a Postgres-only backup restores a
database that references snapshots/publishes whose actual package files
no longer exist; a filesystem-only backup restores content with no
database to make sense of it.

## Usage

```bash
sudo ./scripts/backup.sh backup /path/to/backup/dir
# writes:
#   /path/to/backup/dir/groundctl-backup-<timestamp>.pgdump
#   /path/to/backup/dir/groundctl-backup-<timestamp>-var-lib-groundctl.tar.gz

sudo ./scripts/backup.sh restore /path/to/backup/dir/groundctl-backup-<timestamp> [--force]
```

`restore` refuses to proceed if `/var/lib/groundctl` already has content,
unless `--force` is passed — a restore is destructive to whatever's
already there (the database restore uses `pg_restore --clean --if-exists`,
which drops existing objects before recreating them; `--force` also drops
and recreates the `groundctl` database outright first).

After a restore, restart every service so in-memory state matches the
restored data:

```bash
systemctl restart groundctl groundctl-worker groundctl-beat aptly
```

## Recommended schedule

Not auto-installed — backup destinations are environment-specific (a
mounted NFS share, an object-storage sync target, etc.), which this
project has no way to assume. A systemd timer is the natural fit if you
want this automated:

```ini
# /etc/systemd/system/groundctl-backup.service
[Unit]
Description=groundctl backup

[Service]
Type=oneshot
ExecStart=/opt/groundctl-repo/scripts/backup.sh backup /mnt/backups/groundctl
```

```ini
# /etc/systemd/system/groundctl-backup.timer
[Unit]
Description=Daily groundctl backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Then `systemctl enable --now groundctl-backup.timer`. Pair with your own
retention/rotation on the destination directory (this script always
writes a new timestamped pair, never deletes old ones) and, ideally, sync
the destination off-host — a backup that lives on the same disk as what
it's backing up doesn't protect against disk failure.

## What this does NOT cover

- **Point-in-time recovery.** This is a full-dump-based procedure
  (`pg_dump`/`pg_restore`), not WAL archiving — recovery granularity is
  "as of the last backup," not "as of any specific moment." If you need
  sub-daily RPO, set up `pg_basebackup`/WAL archiving separately; this
  script doesn't attempt it.
- **The Ansible SSH keys** (`/etc/groundctl/ansible-keys/`) and **TLS
  cert** (`/etc/groundctl/tls/`) are not included — these are
  regeneratable/re-authorizable, not data you'd lose forever (the shared
  fleet key would need re-authorizing on every managed host if truly
  lost, which is inconvenient but not equivalent to losing content-pool
  data). Back these up separately if you want to avoid that
  re-authorization step after a disaster-recovery restore.
- **`/etc/groundctl/groundctl.env`** (secrets) — same reasoning; also see
  [`docs/secrets.md`](secrets.md) for the encryption-at-rest story for
  this file specifically.
