import { api } from "./client";

export type ServerStatus = "registered" | "bootstrapped" | "unreachable";
export type ServerLifecycleState = "active" | "decommissioned";

export interface ServerCreate {
  hostname: string;
  ip_address: string;
  ssh_user: string;
  environment_id: string;
  site_id?: string | null;
}

export interface ServerRead {
  id: string;
  hostname: string;
  ip_address: string;
  ssh_user: string;
  environment_id: string;
  site_id: string | null;
  status: ServerStatus;
  lifecycle_state: ServerLifecycleState;
  last_seen_at: string | null;
  created_at: string;
}

export interface ServerFactRead {
  server_id: string;
  os_distribution: string | null;
  os_version: string | null;
  kernel: string | null;
  uptime_seconds: number | null;
  disk: Record<string, unknown>[];
  services: Record<string, unknown>[];
  gathered_at: string;
}

export interface ListServersParams {
  environment_id?: string;
  host_group_id?: string;
  site_id?: string;
  lifecycle_state?: ServerLifecycleState;
  limit?: number;
  offset?: number;
}

export function listServers(params: ListServersParams = {}): Promise<ServerRead[]> {
  return api.get<ServerRead[]>("/servers", params);
}

export function createServer(payload: ServerCreate): Promise<ServerRead> {
  return api.post<ServerRead>("/servers", payload);
}

export function getServer(serverId: string): Promise<ServerRead> {
  return api.get<ServerRead>(`/servers/${serverId}`);
}

export function getLatestServerFacts(serverId: string): Promise<ServerFactRead> {
  return api.get<ServerFactRead>(`/servers/${serverId}/facts`);
}

export function getServerFactsHistory(
  serverId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ServerFactRead[]> {
  return api.get<ServerFactRead[]>(`/servers/${serverId}/facts/history`, params);
}

export function decommissionServer(serverId: string): Promise<ServerRead> {
  return api.post<ServerRead>(`/servers/${serverId}/decommission`);
}

// site_id is a query param on this endpoint, not a body field (confirmed
// from app/routers/servers.py: `def assign_server_site(server_id, site_id:
// uuid.UUID | None = None, ...)`). Pass null/undefined to unassign.
export function assignServerSite(serverId: string, siteId: string | null): Promise<ServerRead> {
  return api.post<ServerRead>(`/servers/${serverId}/assign-site`, undefined, { site_id: siteId ?? undefined });
}

// Changing this alone doesn't move any packages — the host only actually
// starts pulling from the new environment once it re-bootstraps (see
// triggerBootstrap in api/jobs.ts) or, once deployed, its next beacon
// checkin.
export function assignServerEnvironment(
  serverId: string,
  environmentId: string,
  reason?: string,
): Promise<ServerRead> {
  return api.post<ServerRead>(`/servers/${serverId}/assign-environment`, {
    environment_id: environmentId,
    reason: reason || undefined,
  });
}

// --- Beacon ------------------------------------------------------------

export interface BeaconStateRead {
  server_id: string;
  config_serial: number;
  applied_config_serial: number | null;
  pending_reconciliation: boolean;
  last_checkin_at: string | null;
  last_apply_status: string | null;
  last_apply_detail: string | null;
  last_facts_pushed_at: string | null;
  agent_version: string | null;
}

export interface BeaconTokenRead {
  id: string;
  server_id: string;
  name: string | null;
  expires_at: string | null;
  revoked: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface BeaconTokenCreateResponse extends BeaconTokenRead {
  // Raw token — present only in the response to issueBeaconToken, never
  // again afterward (listBeaconTokens never includes it).
  token: string;
}

// 404s if the server has never checked in (not beacon-managed) — callers
// should treat that as "no beacon" rather than a real error, same as
// getLatestServerFacts before any facts exist.
export function getBeaconState(serverId: string): Promise<BeaconStateRead> {
  return api.get<BeaconStateRead>(`/servers/${serverId}/beacon-state`);
}

export function issueBeaconToken(serverId: string, name?: string): Promise<BeaconTokenCreateResponse> {
  return api.post<BeaconTokenCreateResponse>(`/servers/${serverId}/beacon-token`, { name: name || undefined });
}

export function listBeaconTokens(serverId: string): Promise<BeaconTokenRead[]> {
  return api.get<BeaconTokenRead[]>(`/servers/${serverId}/beacon-tokens`);
}

export function revokeBeaconToken(serverId: string, tokenId: string): Promise<BeaconTokenRead> {
  return api.post<BeaconTokenRead>(`/servers/${serverId}/beacon-tokens/${tokenId}/revoke`);
}
