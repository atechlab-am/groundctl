# Web UI

ROADMAP Phase 8 added a full-featured web console at `ui/` — a Vite +
React + TypeScript SPA covering every resource router with real list,
detail, and action screens, not just a read-only dashboard.

New to groundctl? [`docs/first-environment.md`](first-environment.md) walks
through setting up your first repository → content view → environment →
server end to end via these screens.

## Screens

| Area | Covers |
|---|---|
| Dashboard | Fleet status counts, environments and their current published version, recent jobs |
| Repositories | List, create, trigger sync |
| Content Views | Create, view filters/versions, add filter, publish (see gap below — no list/detail GET on the backend) |
| Lifecycle Environments | List, create, promote, rollback, fetch GPG key |
| Servers | List, detail (facts, facts history, job history), decommission, assign to site |
| Jobs | List (filterable), detail with full log viewer, trigger bootstrap/apply-updates/gather-facts/bulk-apply-updates/manage-package/run-command, cancel |
| Compliance | Package search across the fleet, trigger per-server check |
| Errata | List, detail, affected-servers |
| Host Groups | List, detail, manage membership |
| Activation Keys | List, create (raw token shown once), revoke |
| Sites | List, detail, register/view relay, manage synced environments |
| Audit Logs | Filterable table, CSV export (admin-only) |
| Documentation | Renders `docs/*.md` in-app (list + per-doc markdown view) — see `GET /api/docs` below |

RBAC-gated actions match the API exactly: viewer sees read-only screens,
operator gets create/action forms, admin additionally sees `run-command`
and the entire Audit Logs area. Hiding an action in the UI for a role that
can't use it is a convenience, not a security boundary — the server-side
`require_role()` checks in `app/routers/` are the real enforcement, and a
direct API call still gets a 403 regardless of what the UI shows.

## Architecture

- Same-origin: the built SPA (`ui/dist/`) is copied to `app/static/` and
  served directly by the FastAPI app via a custom `SPAStaticFiles` mount
  at `/` in `app/main.py`, added *after* every API router so it can never
  shadow an API route. No CORS, no separate nginx routing — nginx's role
  is unchanged (it still serves only the published apt repo tree).
- **Deep-link fallback**: Starlette's `StaticFiles(html=True)` only falls
  back to `index.html` for a directory-shaped miss — a bare client route
  like `/login` has no on-disk match and *raises* an `HTTPException(404)`
  rather than returning one, so `html=True` alone does not make
  client-side routing survive a hard refresh. `SPAStaticFiles` catches
  that 404 and retries against `index.html`, but only for route-shaped
  paths (no file extension on the last segment) — a genuinely missing
  asset (bad JS/CSS reference) still 404s for real, it doesn't silently
  serve HTML. Verified live: `/login`, `/servers/<id>`, and other deep
  links return the SPA shell; `/assets/<missing>.js` still 404s.
- **Auth**: a second, additive auth flow alongside the existing Bearer-only
  API. `POST /api/auth/ui-login` sets the refresh token as an httpOnly,
  `Secure`, `SameSite=lax` cookie scoped to `/api/auth` instead of returning it
  in the JSON body; the 15-minute access token is held in memory only
  (`AuthContext`, `ui/src/auth/`) — never `localStorage`/`sessionStorage`.
  `POST /api/auth/ui-refresh` reads the cookie and rotates it. The SPA calls
  `ui-refresh` once on load (silently restoring a session from the cookie)
  and again every 12 minutes to stay ahead of the 15-minute expiry.
  `ui/src/api/client.ts`'s fetch wrapper attaches `Authorization: Bearer`
  on every call and retries exactly once through a fresh refresh on a 401
  before giving up and redirecting to `/login`. Verified live end-to-end:
  login sets the cookie with the correct flags, `/api/auth/me` returns the
  right user, refresh rotates the cookie, logout revokes it, and a second
  refresh after logout correctly 401s.
- **Data fetching**: TanStack Query for caching/mutations. **Routing**:
  `react-router-dom`. **Components**: shadcn/ui (copy-in source under
  `ui/src/components/ui/`, not a runtime dependency) + Tailwind.

## Known gaps

- **No `GET /api/content-views` list or `GET /api/content-views/{id}` detail
  endpoint exists on the backend.** Content views can only be created
  (which returns the full object) and then referenced by ID elsewhere
  (e.g. `LifecycleEnvironmentRead.content_view_id`). The Content Views
  screen works around this client-side (`useKnownContentViews.ts`) by
  remembering every content view this browser has created/viewed in
  `localStorage` — a real, visible limitation (a fresh browser profile
  won't see content views created elsewhere), not a substitute for the
  missing backend endpoint. Add `GET /api/content-views` if this becomes a
  real pain point; it's a small, additive router change.
- Audit-log CSV export (`GET /api/audit-logs/export`, admin-only, Bearer-auth)
  is fetched as a blob and downloaded via a temporary object URL rather
  than a plain `<a href>` — a Bearer-authenticated endpoint can't be a
  plain link.
- No browser-based click-through/visual verification was performed for
  this phase (no headless browser tooling in the dev environment used to
  build it) — verification was `npm run build` (strict TypeScript, zero
  errors) plus real HTTP-level exercise of the auth flow and API calls via
  curl against a live backend. Functional correctness of individual forms'
  interactive behavior (validation messages, dialog states, etc.) has not
  been visually confirmed.

## Local development

```bash
cd ui
npm install        # first time only
npm run dev        # :5173, proxies /api/* to http://127.0.0.1:8000
npm run build       # tsc -b && vite build -> ui/dist/
```

`npm run dev`'s cookie-based auth will not persist in a real browser
unless the backend it's proxying to serves over HTTPS — `/api/auth/ui-login`
sets `Secure` on the refresh cookie by design (see `docs/https.md`), and
browsers refuse to store `Secure` cookies over plain HTTP. Point the dev
server at a real HTTPS-enabled local instance (`install.sh` sets this up
by default) to exercise the full cookie-persisted login flow; login and
Bearer-token API calls still work over HTTP, only the cookie's
persistence-across-reload behavior needs HTTPS.

Production deploys never hit this: `install.sh` builds the UI and serves
it from the same HTTPS origin as the API (see `docs/install.md`).
