import { api, apiRequestRaw } from "./client";

// Matches Satellite's own "New Lifecycle Environment" dialog — name,
// description, prior. Every content view auto-creates its own "Library"
// root environment (see LifecycleEnvironmentRead.is_library) — this
// interface is for every OTHER environment, always scoped to exactly one
// content view. content_view_id is required unless prior_environment_id is
// set, in which case it's inherited from the prior environment instead.
// release/publish_prefix stay deferred to the environment's first promote
// (see PromoteRequest below), derived from whatever version gets pushed to
// it, instead of asked here.
export interface LifecycleEnvironmentCreate {
  name: string;
  description?: string | null;
  // Required unless prior_environment_id is set.
  content_view_id?: string | null;
  // Omit to start a brand-new promotion path at position 0 on
  // content_view_id. Set to insert this environment immediately after
  // another one in its existing path (content_view_id is then inherited
  // from the prior environment, and must not be set to a different one).
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
  // Always set now (explicit at creation, inherited from a prior
  // environment, or auto-set for Library) — no longer deferred to first
  // promote. Still nullable in the type for legacy pre-Library rows.
  content_view_id: string | null;
  // True only for the one auto-created root environment per content view
  // (name "Library", position 0) — see create_content_view server-side.
  // Protected from delete/rename/reparent; never creatable through
  // LifecycleEnvironmentCreate.
  is_library: boolean;
  release: string | null;
  publish_prefix: string | null;
  current_version_id: string | null;
  gpg_key_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromoteRequest {
  // Required on an environment's FIRST promote (release is still null) —
  // that's the moment release/publish_prefix get derived and locked in.
  // content_view_id is already set from creation. Omit on every later
  // promote to promote the content view's latest version.
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
  // Exact match — every environment on this content view, Library
  // included.
  content_view_id?: string;
  // Matches content_view_id == target OR content_view_id IS NULL — the
  // null arm only still matters for legacy pre-Library rows now that
  // content_view_id is always set on new environments. Kept distinct from
  // content_view_id above for that legacy case.
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
