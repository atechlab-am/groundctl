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

### Publish a version — and meet your content view's Library

Still on the Content Views page, click **Create** and this happens
automatically: the content view cuts its first immutable **content view
version** (a snapshot of every member repository's current contents,
frozen together) and publishes it to an auto-created root environment
called **Library** — matching Satellite exactly. You don't create Library
yourself, can't rename or delete it, and it's already live the moment the
content view exists.

Everything you promote later flows outward from Library — first to
whatever environment you chain onto it (e.g. QA), then the next
(Dev), then the next (Prod), typically converging so every environment in
the path eventually carries the same patch level. Click **Publish** again
any time member repositories change to cut a new version (still lands in
Library first).

## 3. Lifecycle Environments — the promotion path from Library outward

**Environments** page → **New environment**. Creation matches Satellite's
own "New Lifecycle Environment" dialog, plus which content view it
belongs to:

| Field | What it means |
|---|---|
| Name | Display name, e.g. `jammy-qa`. Also becomes the publish URL segment once you promote something to it (see below), so keep it something you'd want in a URL. |
| Description | Free text, optional. |
| Content view | Required — every environment belongs to exactly one content view, same as its Library. |
| Prior | Which environment this one comes right after in its promotion path — defaults to that content view's Library if left blank, so a fresh environment naturally starts one step out from Library (e.g. `Library → jammy-qa`, then `jammy-qa → jammy-dev`, then `jammy-dev → jammy-prod`). Position N can only be promoted into once position N-1 in the same path currently has that version live. |

GPG signing and publish prefix are **not** asked here — none of it is
needed until you actually publish something to the environment. Create
it now; it starts as an empty shell with nothing published (Library, by
contrast, is never an empty shell — it's live from the moment its content
view exists).

### Promote — actually point it at content (and lock in the rest)

Click **Promote** and pick the content view version you just published
(or leave it to promote whatever's newest). This is the step that derives
`release` from the content view's first repository and sets the publish
prefix to the environment's name — same "just push a content view to it"
flow as Satellite. It's also the step that actually makes the environment
serve real package data. The content view itself was already fixed at
creation, so this step never changes which content view an environment
belongs to.

No GPG key configured yet? You'll be asked to either set one first
(**Edit** on the environment page, or `PATCH /api/lifecycle-environments/{id}`)
or explicitly confirm unsigned publishing — see
[`docs/gpg-signing.md`](gpg-signing.md). Unsigned means managed hosts
trust this repo's metadata unverified (`[trusted=yes]`) — fine for a
trusted network, not for anything exposed.

Your environment is now live at
`https://<fleet-hostname>:<nginx-port>/<name>/`.

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
