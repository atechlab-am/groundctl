import { api } from "./client";
import type { LifecycleEnvironmentRead } from "./environments";

export type RelaySyncStatus = "never_synced" | "healthy" | "stale" | "failed";

export interface SiteCreate {
  name: string;
  description?: string | null;
}

export interface SiteRead {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface RelayCreate {
  hostname: string;
  ssh_user: string;
}

export interface RelayRead {
  id: string;
  site_id: string;
  hostname: string;
  ssh_user: string;
  sync_status: RelaySyncStatus;
  last_sync_time: string | null;
  content_size_bytes: number | null;
  created_at: string;
}

export interface SiteEnvironmentsUpdate {
  environment_ids: string[];
}

export function listSites(params: { limit?: number; offset?: number } = {}): Promise<SiteRead[]> {
  return api.get<SiteRead[]>("/sites", params);
}

export function createSite(payload: SiteCreate): Promise<SiteRead> {
  return api.post<SiteRead>("/sites", payload);
}

export function getSite(siteId: string): Promise<SiteRead> {
  return api.get<SiteRead>(`/sites/${siteId}`);
}

export function createRelay(siteId: string, payload: RelayCreate): Promise<RelayRead> {
  return api.post<RelayRead>(`/sites/${siteId}/relay`, payload);
}

export function getRelay(siteId: string): Promise<RelayRead> {
  return api.get<RelayRead>(`/sites/${siteId}/relay`);
}

export function listSiteEnvironments(
  siteId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<LifecycleEnvironmentRead[]> {
  return api.get<LifecycleEnvironmentRead[]>(`/sites/${siteId}/environments`, params);
}

export function replaceSiteEnvironments(
  siteId: string,
  payload: SiteEnvironmentsUpdate,
): Promise<LifecycleEnvironmentRead[]> {
  return api.put<LifecycleEnvironmentRead[]>(`/sites/${siteId}/environments`, payload);
}
