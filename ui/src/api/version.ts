import { api } from "./client";

export interface VersionRead {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  last_checked_at: string | null;
}

export interface ChangelogRead {
  content: string;
}

export function getVersion(): Promise<VersionRead> {
  return api.get<VersionRead>("/version");
}

// Admin-only, synchronous GitHub lookup — bypasses the daily scheduled
// check (up to 24h stale) for an immediate refresh.
export function checkVersionNow(): Promise<VersionRead> {
  return api.post<VersionRead>("/version/check-now");
}

export function getChangelog(): Promise<ChangelogRead> {
  return api.get<ChangelogRead>("/version/changelog");
}
