# Releasing

Versioning follows [Semantic Versioning](https://semver.org/):
`MAJOR.MINOR.PATCH` — `MAJOR` for breaking changes, `MINOR` for
backwards-compatible features, `PATCH` for backwards-compatible bug fixes.

## Source of truth

- **[`VERSION`](../VERSION)** — a single line, e.g. `0.1.0`. This is what CI
  reads to decide whether a push to `dev` should become a release. Nothing
  else in the repo (not `pyproject.toml`, not `package.json`) is the
  canonical version — if you change one, change `VERSION` too, in the same
  commit.
- **[`CHANGELOG.md`](../CHANGELOG.md)** — human-readable release notes,
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Add
  entries under `## [Unreleased]` as you go; when you're ready to cut a
  release, rename that section to `## [X.Y.Z] - YYYY-MM-DD` and start a
  fresh empty `## [Unreleased]` above it.

## Branch model

- **`dev`** — integration branch. Feature branches merge here. CI runs on
  every push.
- **`main`** — released/stable. Only ever updated by the release workflow
  fast-forwarding it to `dev` — never push to `main` directly (the release
  workflow will fail loudly with a merge-conflict-style error if `main` has
  diverged, rather than silently overwriting anything).

## Cutting a release

1. On a branch off `dev`, bump `VERSION` and add/rename the `CHANGELOG.md`
   section for the new version, in the same commit as (or a commit
   immediately following) whatever functional change you're shipping.
2. Merge to `dev`.
3. `.github/workflows/ci.yml` runs automatically. If it passes,
   `.github/workflows/release.yml` triggers (via `workflow_run`, watching
   for `CI` completing on `dev`):
   - Reads `VERSION`. If a tag `vX.Y.Z` for that version already exists,
     it's a no-op (nothing to release) — this is what makes a normal,
     non-version-bumping push to `dev` safe; it runs CI but never creates
     a release.
   - Otherwise: extracts the matching `## [X.Y.Z]` section from
     `CHANGELOG.md`, fast-forwards `main` to `dev`, tags `main` as
     `vX.Y.Z`, and creates a GitHub Release with those notes.

If `CHANGELOG.md` has no section matching `VERSION`, the release still
happens but with an empty body and a workflow warning — always add the
CHANGELOG section, don't rely on this fallback.

## Why fast-forward, not merge commit

`main` should be an exact mirror of whatever commit on `dev` passed CI and
got tagged — a fast-forward guarantees that; a merge commit would introduce
a commit on `main` that never itself ran through CI. If `main` has
diverged (e.g. someone pushed a hotfix directly to it, which shouldn't
happen but isn't prevented at the git level), the fast-forward fails and
the release workflow errors out rather than force-pushing over the
divergence — resolve that by hand (typically: fold the hotfix back into
`dev` first).
