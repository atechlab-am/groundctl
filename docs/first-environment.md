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

Still on the Content Views page, click **Create** — this cuts the content
view's first immutable **content view version** (a snapshot of every
member repository's current contents, frozen together). Nothing is
published anywhere yet; a content view is its own thing, independent of
any lifecycle environment. Click **Publish** again any time member
repositories change to cut a new version.

## 3. Lifecycle Environments — promotion paths, not content-view slots

**Environments** page → **New environment**. Creation matches Satellite's
own "New Lifecycle Environment" dialog — an environment is pure
**promotion-path structure**, with no content view of its own:

| Field | What it means |
|---|---|
| Name | Display name, e.g. `QA`, `Dev`, `Prod`. |
| Description | Free text, optional. |
| Prior | Which environment this one comes right after in the single promotion path (e.g. `Library → QA` means QA's prior is Library). Leave blank to append at the end of the path — the very first environment you ever create automatically gets `Library` created ahead of it as the root, so you never create Library yourself. Setting Prior to an environment that already has a successor inserts this one there instead, shifting everything after it back by one position. Position N can only be promoted into once position N-1 in the path currently has that content view's version live. |

There is exactly **one** promotion path in the whole system — no
independent second path, no manual Library creation. Content view, GPG
signing, and publish prefix are **not** asked here — none of it is needed
until you actually assign a content view to the environment. Create it
now; it starts empty, with nothing assigned.

An environment can be deleted (from its row's **Delete** action) once
nothing is assigned to it — no content views, no servers. The page shows
both counts per environment; unassign/reassign first if either is
nonzero. Library itself isn't protected — it deletes like any other
environment once empty, though in practice it rarely will be.

### Assign a content view — this is where publishing actually happens

Any number of content views can be assigned to the same environment,
independently. On the environment's **Content views** panel, click
**Assign content view**, pick the content view and the version to publish,
and (if it's the first time this content view has been assigned anywhere)
either set a GPG key or explicitly confirm unsigned publishing.

This single action creates the assignment AND publishes it — deriving
`release` from the content view's first repository and setting the
publish prefix to `<environment-name>/<content-view-name>`. It's the step
that actually makes the environment serve that content view's package
data. Later promotes for the same assignment (a new version, or rolling
back) reuse the signing/release choice made here.

No GPG key configured? You'll be asked to either set one at assignment
time or explicitly confirm unsigned publishing — see
[`docs/gpg-signing.md`](gpg-signing.md). Unsigned means managed hosts
trust this repo's metadata unverified (`[trusted=yes]`) — fine for a
trusted network, not for anything exposed.

The assignment is now live at
`https://<fleet-hostname>:<nginx-port>/<environment-name>/<content-view-name>/`.
Repeat for as many content views as this environment should carry — e.g.
a `jammy-baseline` content view and a separate `security-only` content
view can both live in the same `Prod` environment, each promoted on its
own schedule.

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
server's detail page, or `POST /api/jobs/bootstrap/{id}`) — this writes one
apt source file per content view assigned to the environment
(`/etc/apt/sources.list.d/groundctl-<environment>-<content-view>.list`),
installs each one's GPG key if signing is on, and swaps in a per-host SSH
key for future connections.

From here, `apt update && apt upgrade` on that host sees every content
view assigned to its environment. Promoting a new content view version
later and re-promoting that assignment is how you roll out updates — see
[`docs/quickstart.md`](quickstart.md) sections 8 onward for patching an
environment, rollback, and errata-driven filters.
