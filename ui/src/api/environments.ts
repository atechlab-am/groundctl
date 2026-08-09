import { api, apiRequestRaw } from "./client";

export interface LifecycleEnvironmentCreate {
  name: string;
  path_name: string;
  position: number;
  content_view_id: string;
  distro: string;
  release: string;
  publish_prefix: string;
  // Backend validator: gpg_key_id is required unless allow_unsigned=true is
  // explicitly set (see app/schemas.py's LifecycleEnvironmentCreate).
  gpg_key_id?: string | null;
  allow_unsigned: boolean;
}

export interface LifecycleEnvironmentRead {
  id: string;
  name: string;
  path_name: string;
  position: number;
  content_view_id: string;
  distro: string;
  release: string;
  publish_prefix: string;
  current_version_id: string | null;
  gpg_key_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromoteRequest {
  content_view_version_id?: string | null;
}

export interface PromoteResponse {
  id: string;
  current_version_id: string;
  publish_prefix: string;
  published_url: string;
}

export interface RollbackRequest {
  content_view_version_id: string;
}

export interface ListEnvironmentsParams {
  path_name?: string;
  content_view_id?: string;
  limit?: number;
  offset?: number;
}

export function listLifecycleEnvironments(
  params: ListEnvironmentsParams = {},
): Promise<LifecycleEnvironmentRead[]> {
  return api.get<LifecycleEnvironmentRead[]>("/lifecycle-environments", params);
}

export function createLifecycleEnvironment(
  payload: LifecycleEnvironmentCreate,
): Promise<LifecycleEnvironmentRead> {
  return api.post<LifecycleEnvironmentRead>("/lifecycle-environments", payload);
}

export function promoteEnvironment(
  environmentId: string,
  payload: PromoteRequest,
): Promise<PromoteResponse> {
  return api.post<PromoteResponse>(`/lifecycle-environments/${environmentId}/promote`, payload);
}

export function rollbackEnvironment(
  environmentId: string,
  payload: RollbackRequest,
): Promise<PromoteResponse> {
  return api.post<PromoteResponse>(`/lifecycle-environments/${environmentId}/rollback`, payload);
}

// Returns the raw ASCII-armored GPG public key text (media type
// application/pgp-keys). 404 if the environment has no gpg_key_id
// configured, 502 if the export itself failed server-side.
export async function fetchEnvironmentGpgKey(environmentId: string): Promise<string> {
  const response = await apiRequestRaw(`/lifecycle-environments/${environmentId}/gpg-key`);
  return response.text();
}
