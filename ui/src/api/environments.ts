import { api, apiRequestRaw } from "./client";

// Matches Satellite's own "New Lifecycle Environment" dialog — name,
// description, prior. There is exactly ONE promotion path in the whole
// system, always rooted at an auto-created "Library" environment. An
// environment is pure promotion-path structure with NO content view of its
// own — any number of content views get assigned to it afterward,
// independently, via EnvironmentContentViewCreate below.
export interface LifecycleEnvironmentCreate {
  name: string;
  description?: string | null;
  // Omit to append at the end of the single path (Library is auto-created
  // as the root first if this is the very first environment). Set to
  // insert this environment immediately after another one already in the
  // path — everything past that point shifts back to make room.
  prior_environment_id?: string | null;
}

export interface LifecycleEnvironmentUpdate {
  description?: string | null;
}

export interface LifecycleEnvironmentRead {
  id: string;
  name: string;
  description: string | null;
  path_name: string;
  position: number;
  created_at: string;
  updated_at: string;
  // How many content views / servers currently reference this environment
  // — drives the delete guard (DELETE is blocked while either is nonzero).
  content_view_count: number;
  host_count: number;
}

// Assigns a content view to an environment AND performs its first promote
// in one call — there's no useful "assigned but never published" state
// worth exposing separately.
export interface EnvironmentContentViewCreate {
  content_view_id: string;
  // Required — no "latest" default on a first promote.
  content_view_version_id: string;
  gpg_key_id?: string | null;
  // Required unless gpg_key_id is set.
  allow_unsigned?: boolean;
}

export interface EnvironmentContentViewRead {
  id: string;
  environment_id: string;
  content_view_id: string;
  current_version_id: string | null;
  release: string | null;
  publish_prefix: string | null;
  gpg_key_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromoteRequest {
  // Omit to publish-if-needed and promote the content view's latest
  // version. Every EnvironmentContentView this applies to has already had
  // its first promote (see EnvironmentContentViewCreate) — release/
  // publish_prefix/gpg_key_id are already locked in by the time this runs.
  content_view_version_id?: string | null;
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

// 409 if content_view_count or host_count is nonzero — unassign/reassign
// first.
export function deleteLifecycleEnvironment(environmentId: string): Promise<void> {
  return api.delete<void>(`/lifecycle-environments/${environmentId}`);
}

export function listEnvironmentContentViews(environmentId: string): Promise<EnvironmentContentViewRead[]> {
  return api.get<EnvironmentContentViewRead[]>(`/lifecycle-environments/${environmentId}/content-views`);
}

export function assignContentViewToEnvironment(
  environmentId: string,
  payload: EnvironmentContentViewCreate,
): Promise<EnvironmentContentViewRead> {
  return api.post<EnvironmentContentViewRead>(`/lifecycle-environments/${environmentId}/content-views`, payload);
}

export function unassignContentViewFromEnvironment(environmentId: string, contentViewId: string): Promise<void> {
  return api.delete<void>(`/lifecycle-environments/${environmentId}/content-views/${contentViewId}`);
}

export function promoteEnvironmentContentView(
  environmentId: string,
  contentViewId: string,
  payload: PromoteRequest,
): Promise<PromoteResponse> {
  return api.post<PromoteResponse>(
    `/lifecycle-environments/${environmentId}/content-views/${contentViewId}/promote`,
    payload,
  );
}

export function rollbackEnvironmentContentView(
  environmentId: string,
  contentViewId: string,
  payload: RollbackRequest,
): Promise<PromoteResponse> {
  return api.post<PromoteResponse>(
    `/lifecycle-environments/${environmentId}/content-views/${contentViewId}/rollback`,
    payload,
  );
}

// Returns the raw ASCII-armored GPG public key text (media type
// application/pgp-keys). 404 if this assignment has no gpg_key_id
// configured, 502 if the export itself failed server-side.
export async function fetchEnvironmentContentViewGpgKey(environmentId: string, contentViewId: string): Promise<string> {
  const response = await apiRequestRaw(`/lifecycle-environments/${environmentId}/content-views/${contentViewId}/gpg-key`);
  return response.text();
}
