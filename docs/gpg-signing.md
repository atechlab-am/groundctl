# GPG signing

## Current state: on by default, unsigned as explicit opt-in

Signing is a property of an **(environment, content view) assignment**
(`EnvironmentContentView`, `app/models.py`), not of the environment
itself — an environment is pure promotion-path structure with no content
of its own. `POST /lifecycle-environments/{id}/content-views`
(`EnvironmentContentViewCreate`, `app/schemas.py`) requires `gpg_key_id`
unless `allow_unsigned: true` is passed explicitly. `AptlyClient.
publish_snapshot`/`switch_publish` (`app/aptly_client.py`) take a
`gpg_key_id: str | None` parameter and pass
`{"Skip": gpg_key_id is None, "GpgKey": gpg_key_id}` — no longer
hardcoded.

## Generating a key

Signing requires a real GPG key to exist in the keyring of whatever user
runs the groundctl API process (`groundctl`, on the primary — the same
process that calls `gpg --export` at request time):

```
sudo -u groundctl gpg --full-generate-key
```

Use a dedicated key for this purpose, not a personal key — it needs to
live wherever the groundctl app runs and will sign every publish for any
assignment configured to use it. Copy the key's fingerprint (long-form
hex, e.g. `sudo -u groundctl gpg --list-secret-keys --with-colons`) — this
is the `gpg_key_id` passed to
`POST /api/lifecycle-environments/{id}/content-views`.

## How it flows through to clients

1. `POST /api/lifecycle-environments/{id}/content-views` with `gpg_key_id`
   set persists it on the `EnvironmentContentView` row for that
   (environment, content view) pair — this is also that pair's first
   promote, published immediately.
2. Every later `promote`/`rollback` for that same pair reuses
   `ecv.gpg_key_id` in `publish_snapshot`/`switch_publish` — aptly signs
   the Release file with that key on every publish/switch.
3. `GET /api/lifecycle-environments/{id}/content-views/{content_view_id}/gpg-key`
   exports the public half (`gpg --export --armor`), ASCII-armored —
   viewer-role readable, since the public key isn't sensitive.
4. `bootstrap_client.yml` fetches each assigned content view's key
   directly from the **primary's** local keyring (`delegate_to:
   localhost`, not over HTTP) and pushes it to the managed host over the
   same SSH connection used for the rest of bootstrap — this avoids the
   chicken-and-egg problem of needing to already trust HTTPS to fetch the
   thing that makes HTTPS trustworthy. Each key is dearmored into
   `/etc/apt/keyrings/groundctl-<environment>-<content-view>.gpg`.
5. The apt source entry written to
   `/etc/apt/sources.list.d/groundctl-<environment>-<content-view>.list`
   uses `deb [signed-by=/etc/apt/keyrings/groundctl-<environment>-<content-view>.gpg] ...`
   when that assignment's `gpg_key_id` is set. An assignment created with
   `allow_unsigned: true` instead gets `deb [trusted=yes] ...`, and the
   playbook emits a loud `ansible.builtin.debug` warning naming the
   content view — never a silent fallback.

## Opting out

Pass `"allow_unsigned": true` in
`POST /api/lifecycle-environments/{id}/content-views` when `gpg_key_id`
is omitted. This is a deliberate per-assignment choice, not a global
setting — some content views (e.g. a scratch/dev one) may reasonably stay
unsigned in a given environment while production-facing ones require it,
even within the same environment.

## Known gaps

- Key generation itself is a manual, one-time operator step
  (`gpg --full-generate-key`), not automated — a generated-and-thrown-away
  key defeats the purpose of a trust anchor, so this is intentional.
- No key rotation support — changing an assignment's `gpg_key_id` isn't
  validated against previously-published, still-live content signed with
  the old key (there is currently no PATCH for `EnvironmentContentView`
  fields beyond a promote/rollback re-deriving them). Rotating requires
  operator care.
- The export endpoint requires the key to already be present in the
  groundctl process's GPG keyring; it returns `502` if not, rather than
  attempting to generate one.
