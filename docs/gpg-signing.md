# GPG signing

## Current state: on by default, unsigned as explicit opt-in

`LifecycleEnvironmentCreate` requires `gpg_key_id` unless `allow_unsigned: true`
is passed explicitly — a Pydantic validator in `app/schemas.py` rejects
creation otherwise. `AptlyClient.publish_snapshot`/`switch_publish`
(`app/aptly_client.py`) take a `gpg_key_id: str | None` parameter and pass
`{"Skip": gpg_key_id is None, "GpgKey": gpg_key_id}` — no longer hardcoded.

## Generating a key

Signing requires a real GPG key to exist in the keyring of whatever user
runs the groundctl API process (`groundctl`, on the primary — the same
process that calls `gpg --export` at request time):

```
sudo -u groundctl gpg --full-generate-key
```

Use a dedicated key for this purpose, not a personal key — it needs to
live wherever the groundctl app runs and will sign every publish for any
environment configured to use it. Copy the key's fingerprint (long-form
hex, e.g. `sudo -u groundctl gpg --list-secret-keys --with-colons`) — this
is the `gpg_key_id` passed to `POST /lifecycle-environments`.

## How it flows through to clients

1. `POST /lifecycle-environments` with `gpg_key_id` set persists it on the
   `LifecycleEnvironment` row.
2. `promote`/`rollback` pass `environment.gpg_key_id` into
   `publish_snapshot`/`switch_publish` — aptly signs the Release file with
   that key on every publish/switch.
3. `GET /lifecycle-environments/{id}/gpg-key` exports the public half
   (`gpg --export --armor`), ASCII-armored — viewer-role readable, since
   the public key isn't sensitive.
4. `bootstrap_client.yml` fetches the key directly from the **primary's**
   local keyring (`delegate_to: localhost`, not over HTTP) and pushes it to
   the managed host over the same SSH connection used for the rest of
   bootstrap — this avoids the chicken-and-egg problem of needing to
   already trust HTTPS to fetch the thing that makes HTTPS trustworthy. The
   key is dearmored into `/etc/apt/keyrings/groundctl-<environment>.gpg`.
5. The apt source entry written to
   `/etc/apt/sources.list.d/groundctl-<environment>.list` uses
   `deb [signed-by=/etc/apt/keyrings/groundctl-<environment>.gpg] ...` when
   `gpg_key_id` is set. An environment created with `allow_unsigned: true`
   instead gets `deb [trusted=yes] ...`, and the playbook emits a loud
   `ansible.builtin.debug` warning naming the environment — never a silent
   fallback.

## Opting out

Pass `"allow_unsigned": true` in `POST /lifecycle-environments` when
`gpg_key_id` is omitted. This is a deliberate per-environment choice, not a
global setting — some environments (e.g. a scratch/dev content view) may
reasonably stay unsigned while production-facing ones require it.

## Known gaps

- Key generation itself is a manual, one-time operator step
  (`gpg --full-generate-key`), not automated — a generated-and-thrown-away
  key defeats the purpose of a trust anchor, so this is intentional.
- No key rotation support — changing `gpg_key_id` on an existing
  environment isn't validated against previously-published, still-live
  content signed with the old key. Rotating requires operator care.
- The export endpoint requires the key to already be present in the
  groundctl process's GPG keyring; it returns `502` if not, rather than
  attempting to generate one.
