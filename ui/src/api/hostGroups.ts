import { api } from "./client";
import type { ServerRead } from "./servers";

export interface HostGroupCreate {
  name: string;
  description?: string | null;
  default_environment_id?: string | null;
}

export interface HostGroupRead {
  id: string;
  name: string;
  description: string | null;
  default_environment_id: string | null;
  created_at: string;
}

export interface HostGroupMembershipUpdate {
  server_ids: string[];
}

export function listHostGroups(params: { limit?: number; offset?: number } = {}): Promise<HostGroupRead[]> {
  return api.get<HostGroupRead[]>("/host-groups", params);
}

export function createHostGroup(payload: HostGroupCreate): Promise<HostGroupRead> {
  return api.post<HostGroupRead>("/host-groups", payload);
}

export function getHostGroup(hostGroupId: string): Promise<HostGroupRead> {
  return api.get<HostGroupRead>(`/host-groups/${hostGroupId}`);
}

export function listHostGroupMembers(
  hostGroupId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ServerRead[]> {
  return api.get<ServerRead[]>(`/host-groups/${hostGroupId}/members`, params);
}

// Full replace, not add/remove — send the complete desired member set.
export function replaceHostGroupMembers(
  hostGroupId: string,
  payload: HostGroupMembershipUpdate,
): Promise<ServerRead[]> {
  return api.put<ServerRead[]>(`/host-groups/${hostGroupId}/members`, payload);
}
