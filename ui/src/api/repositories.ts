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
  last_synced_at: string | null;
  // Actual on-disk size aptly reports as of last_synced_at; null until the
  // first successful sync completes.
  size_bytes: number | null;
  last_sync_job_id: string | null;
  created_at: string;
}

export interface ListRepositoriesParams {
  distribution?: string;
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
