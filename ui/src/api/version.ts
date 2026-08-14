import { api } from "./client";

export interface VersionRead {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  last_checked_at: string | null;
}

export function getVersion(): Promise<VersionRead> {
  return api.get<VersionRead>("/version");
}
