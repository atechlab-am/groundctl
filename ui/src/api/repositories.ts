import { api } from "./client";
import type { JobRead } from "./jobs";

export interface RepositoryCreate {
  name: string;
  archive_url: string;
  distribution: string;
  components: string[];
  architectures: string[];
}

export interface RepositoryRead {
  id: string;
  name: string;
  archive_url: string;
  distribution: string;
  components: string[];
  architectures: string[];
  // NULL = ungrouped. See Product — purely organizational, never affects
  // sync/publish/content-view behavior.
  product_id: string | null;
  last_synced_at: string | null;
  // Actual on-disk size aptly reports as of last_synced_at; null until the
  // first successful sync completes.
  size_bytes: number | null;
  // Package count from that same sync pass; null under the same condition
  // as size_bytes (never synced yet).
  package_count: number | null;
  // Computed by the server at read time — "never_synced" if last_synced_at
  // is null, "stale" if older than the admin-configurable threshold
  // (Settings > System), "healthy" otherwise. Display-only.
  health_status: "healthy" | "stale" | "never_synced";
  last_sync_job_id: string | null;
  // Most recent Job of any kind (sync/update/delete) — unlike
  // last_sync_job_id, tracks Edit/Delete too, so the UI can restore live
  // status for whichever action was running after a page reload.
  last_job_id: string | null;
  // Whether the nightly scheduled sweep includes this repository. Defaults
  // true on creation — manual sync always works regardless of this flag.
  auto_sync_enabled: boolean;
  created_at: string;
}

export interface ListRepositoriesParams {
  distribution?: string;
  product_id?: string;
  limit?: number;
  offset?: number;
}

export function listRepositories(params: ListRepositoriesParams = {}): Promise<RepositoryRead[]> {
  return api.get<RepositoryRead[]>("/repositories", params);
}

export function createRepository(payload: RepositoryCreate): Promise<RepositoryRead> {
  return api.post<RepositoryRead>("/repositories", payload);
}

export function getRepository(name: string): Promise<RepositoryRead> {
  return api.get<RepositoryRead>(`/repositories/${encodeURIComponent(name)}`);
}

// DB-only toggle, no aptly call — unlike sync/edit/delete this is
// synchronous and immediate, not a tracked Job.
export function updateRepositoryAutoSync(name: string, autoSyncEnabled: boolean): Promise<RepositoryRead> {
  return api.patch<RepositoryRead>(`/repositories/${encodeURIComponent(name)}/auto-sync`, {
    auto_sync_enabled: autoSyncEnabled,
  });
}

export interface RepositoryUpdate {
  archive_url: string;
  distribution: string;
  components: string[];
  architectures: string[];
}

// Returns the update Job (async, tracked) rather than the Repository —
// aptly has no in-place edit for a mirror's ArchiveURL/Distribution/
// Components, so this deletes and recreates the aptly mirror under the
// same Repository row, same slow-delete risk syncRepository/
// deleteRepository already run as tracked Jobs for. last_synced_at/
// size_bytes reset once the job actually runs — the new mirror hasn't
// synced anything yet.
export function updateRepository(name: string, payload: RepositoryUpdate): Promise<JobRead> {
  return api.put<JobRead>(`/repositories/${encodeURIComponent(name)}`, payload);
}

// Now returns the delete Job (async, tracked), same as syncRepository —
// aptly's mirror delete confirmed live to take long enough to blow a
// synchronous request/response cycle. 409s (thrown before any Job is
// created) if any content view still references this repository.
export function deleteRepository(name: string): Promise<JobRead> {
  return api.delete<JobRead>(`/repositories/${encodeURIComponent(name)}`);
}

export interface RepositoryProbeResult {
  distributions: string[];
}

export function probeRepositoryArchive(archiveUrl: string): Promise<RepositoryProbeResult> {
  return api.post<RepositoryProbeResult>("/repositories/probe", { archive_url: archiveUrl });
}

export interface RepositoryBatchCreate {
  archive_url: string;
  distributions: string[];
  components: string[];
  architectures: string[];
}

export interface RepositoryBatchCreateError {
  distribution: string;
  detail: string;
}

export interface RepositoryBatchCreateResult {
  created: RepositoryRead[];
  errors: RepositoryBatchCreateError[];
}

export function createRepositoriesBatch(payload: RepositoryBatchCreate): Promise<RepositoryBatchCreateResult> {
  return api.post<RepositoryBatchCreateResult>("/repositories/batch", payload);
}

export interface RepositoryEstimateSizeRequest {
  archive_url: string;
  distribution: string;
  components: string[];
  architectures: string[];
}

export interface RepositoryEstimateSizeResult {
  size_bytes: number;
}

export function estimateRepositorySize(
  payload: RepositoryEstimateSizeRequest,
): Promise<RepositoryEstimateSizeResult> {
  return api.post<RepositoryEstimateSizeResult>("/repositories/estimate-size", payload);
}

// name, not id — aptly object names are the primary key here. Now returns
// the sync Job (async, tracked) rather than the Repository — sync runs as a
// Celery task so the caller can link straight to /jobs/{id} for status.
export function syncRepository(name: string): Promise<JobRead> {
  return api.post<JobRead>(`/repositories/${encodeURIComponent(name)}/sync`);
}

// DB-only, no aptly call — assigns or unassigns (productId=null) this
// repository's Product grouping.
export function updateRepositoryProduct(name: string, productId: string | null): Promise<RepositoryRead> {
  return api.patch<RepositoryRead>(`/repositories/${encodeURIComponent(name)}/product`, {
    product_id: productId,
  });
}
