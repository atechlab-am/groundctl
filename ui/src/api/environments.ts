import { api, apiRequestRaw } from "./client";

// Matches Satellite's own "New Lifecycle Environment" dialog — name,
// description, prior. content_view_id/release/publish_prefix are all
// deferred to the environment's first promote (see PromoteRequest below),
// derived from whatever version gets pushed to it, instead of asked here.
export interface LifecycleEnvironmentCreate {
  name: string;
  description?: string | null;
  // Omit to start a brand-new promotion path at position 0. Set to
  // insert this environment immediately after another one in its path.
  prior_environment_id?: string | null;
  gpg_key_id?: string | null;
}

export interface LifecycleEnvironmentUpdate {
  description?: string | null;
  gpg_key_id?: string | null;
}

export interface LifecycleEnvironmentRead {
  id: string;
  name: string;
  description: string | null;
  path_name: string;
  position: number;
  // Null until this environment's first promote — see PromoteRequest.
  content_view_id: string | null;
  release: string | null;
  publish_prefix: string | null;
  current_version_id: string | null;
  gpg_key_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromoteRequest {
  // Required on an environment's FIRST promote (content_view_id is still
  // null) — that's the moment it gets permanently tied to a content view.
  // Omit on every later promote to promote the content view's latest version.
  content_view_version_id?: string | null;
  // Only consulted on a first promote when the environment has no
  // gpg_key_id set — same "signing on by default, explicit opt-out"
  // enforcement LifecycleEnvironmentCreate used to do at creation time.
  allow_unsigned?: boolean;
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
  // Environments already tied to this content view OR never promoted
  // anywhere yet (any content view can be their first) — use this for
  // "which environments can I promote this content view's versions to",
  // not content_view_id (exact-match only, excludes never-promoted ones).
  promotable_for_content_view_id?: string;
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

export function updateLifecycleEnvironment(
  environmentId: string,
  payload: LifecycleEnvironmentUpdate,
): Promise<LifecycleEnvironmentRead> {
  return api.patch<LifecycleEnvironmentRead>(`/lifecycle-environments/${environmentId}`, payload);
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
