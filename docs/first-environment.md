# Setting up your first environment (web UI walkthrough)

Groundctl's content model has a required dependency chain: you can't create a
lifecycle environment until you have a content view, and you can't create a
content view until you have at least one repository. This walks through all
of it via the web UI — see [`docs/quickstart.md`](quickstart.md) for the
same flow via `curl`/the API directly.

Log in at `https://<fleet-hostname>` with the admin account `install.sh`
created (see [`docs/install.md`](install.md)).

## 1. Repositories — mirror an upstream archive

**Repositories** page → **New repository**.

You can browse an upstream archive and pick from what it actually publishes,
rather than typing an exact distribution name blind:

1. Enter an archive URL (default `http://archive.ubuntu.com/ubuntu`) and
   click **Browse**.
2. Check off the distributions you want (e.g. `jammy`, `jammy-updates`,
   `jammy-security` — mirror all three together if you want a
   patch-complete Ubuntu 22.04 stream, not just the base release).
3. Set components (`main,universe`) and architectures (`amd64`), shared
   across every distribution you checked.
4. Click **Create** — this creates one repository per checked distribution
   (an aptly mirror), named after the distribution.

Each new repository needs an initial sync before it has any package data —
click **Sync** on each row. First sync downloads real package files and can
take a while depending on archive size and network speed.

## 2. Content Views — group repositories into one publishable unit

**Content Views** page → **New content view**.

A content view aggregates one or more repositories into a single
versionable, publishable unit — this is how you combine e.g. `jammy` +
`jammy-security` + `jammy-updates` into one patch stream instead of
managing them separately.

Give it a name, select the repositories you just created, and create it.

### Publish a version

Still on the Content Views page, open the one you just created and click
**Publish**. This cuts an immutable **content view version** — a snapshot
of every member repository's current contents, frozen together. You need
at least one published version before you can create a lifecycle
environment against this content view.

## 3. Lifecycle Environments — the thing servers actually point at

**Environments** page → **New environment**.

| Field | What it means |
|---|---|
| Name | Display name, e.g. `jammy-prod` |
| Path name | Groups environments into an ordered promotion chain — e.g. all environments sharing path `default` form one chain (`library` → `dev` → `prod`). If you only need one environment right now, any name works; you can add more at other positions later. |
| Position | 0-based order within the path. Position 0 has no promotion gate; position N can only be promoted into once position N-1 in the same path currently has that version live. Use `0` if this is your first/only environment on this path. |
| Content view | The content view you just published a version for. |
| Distro / release | e.g. `ubuntu` / `jammy` — must match what managed hosts expect in their apt sources. |
| Publish prefix | The URL segment servers' `sources.list` will point at: `https://<fleet-hostname>:<nginx-port>/<publish_prefix>/`. Must be unique across environments. |
| GPG signing | On by default — either supply a `gpg_key_id` (see [`docs/gpg-signing.md`](gpg-signing.md)) or explicitly check **allow unsigned** for a lab/test setup. Unsigned means managed hosts trust this repo's metadata unverified (`[trusted=yes]`) — fine for a trusted network, not for anything exposed. |

Create it. This does **not** publish anything yet — it just creates the
environment shell.

### Promote — actually point it at content

Click **Promote** on the environment. With no `content_view_version_id`
specified, this promotes to the content view's latest published version —
this is the step that actually makes the environment serve real package
data at its publish prefix.

Your environment is now live at
`https://<fleet-hostname>:<nginx-port>/<publish_prefix>/`.

## 4. Add a server

Two ways, matching Satellite's own two enrollment paths:

- **Self-enrollment** (recommended, matches Satellite's "Global
  Registration") — create an **Activation Key** scoped to this
  environment, then run the generated one-line script on the new host.
  See the activation-keys walkthrough in [`docs/quickstart.md`](quickstart.md#13-self-registration-via-activation-key)
  for the field-by-field breakdown (`environment_id`, `host_group_id`,
  `expires_at`, `max_uses`) and exactly what the script does.
- **Manual** — **Servers** page → **New server**, fill in
  hostname/IP/SSH user and pick this environment directly. You'll still
  need to separately authorize groundctl's fleet SSH key
  (`/etc/groundctl/ansible-keys/id_ed25519.pub`) on the host yourself
  before bootstrap can connect — self-enrollment's generated script does
  this step for you automatically, which is the main reason to prefer it.

Either way, once the server exists, trigger **Bootstrap** on it (from the
server's detail page, or `POST /api/jobs/bootstrap/{id}`) — this writes the
environment's apt source into
`/etc/apt/sources.list.d/groundctl-<environment>.list` on the host, installs
the GPG key if signing is on, and swaps in a per-host SSH key for future
connections.

From here, `apt update && apt upgrade` on that host only sees what you've
published to its environment. Promoting a new content view version later
and re-promoting the environment is how you roll out updates — see
[`docs/quickstart.md`](quickstart.md) sections 8 onward for patching an
environment, rollback, and errata-driven filters.
