import { api } from "./client";

export interface ActivationKeyCreate {
  name: string;
  environment_id: string;
  host_group_id?: string | null;
  tags?: string[];
  expires_at?: string | null;
  max_uses?: number | null;
}

// Returned only once, at creation — the raw token is never retrievable
// again (backend stores only a SHA-256 hash). Must be shown to the user in
// a dismissable dialog and never persisted client-side beyond that.
export interface ActivationKeyCreateResponse {
  id: string;
  name: string;
  token: string;
  environment_id: string;
  host_group_id: string | null;
  tags: string[];
  expires_at: string | null;
  max_uses: number | null;
}

export interface ActivationKeyRead {
  id: string;
  name: string;
  environment_id: string;
  host_group_id: string | null;
  tags: string[];
  expires_at: string | null;
  max_uses: number | null;
  use_count: number;
  revoked: boolean;
  created_at: string;
}

export function listActivationKeys(
  params: { limit?: number; offset?: number } = {},
): Promise<ActivationKeyRead[]> {
  return api.get<ActivationKeyRead[]>("/activation-keys", params);
}

export function createActivationKey(payload: ActivationKeyCreate): Promise<ActivationKeyCreateResponse> {
  return api.post<ActivationKeyCreateResponse>("/activation-keys", payload);
}

export function getActivationKey(id: string): Promise<ActivationKeyRead> {
  return api.get<ActivationKeyRead>(`/activation-keys/${id}`);
}

export function revokeActivationKey(id: string): Promise<ActivationKeyRead> {
  return api.post<ActivationKeyRead>(`/activation-keys/${id}/revoke`);
}
