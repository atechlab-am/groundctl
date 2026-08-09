import { api } from "./client";

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

// name, not id — aptly object names are the primary key here.
export function syncRepository(name: string): Promise<RepositoryRead> {
  return api.post<RepositoryRead>(`/repositories/${encodeURIComponent(name)}/sync`);
}
