import { api } from "./client";

export type FilterType = "include" | "exclude" | "errata_since";

export interface ContentViewCreate {
  name: string;
  description?: string | null;
  repository_ids: string[];
}

export interface ContentViewRead {
  id: string;
  name: string;
  description: string | null;
  repository_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ContentViewVersionSnapshot {
  repository_id: string;
  repository_name: string;
  snapshot_name: string;
  component: string;
}

export interface ContentViewVersionRead {
  id: string;
  content_view_id: string;
  version: number;
  snapshots: ContentViewVersionSnapshot[];
  content_hash: string;
  // Total packages across this version's final (post-filter) snapshots —
  // null only for versions cut before this field existed.
  package_count: number | null;
  published_at: string;
}

export interface PublishResponse {
  content_view_version: ContentViewVersionRead;
  version_cut: boolean;
}

export interface ContentViewFilterCreate {
  filter_type: FilterType;
  pattern: string;
}

export interface ContentViewFilterRead {
  id: string;
  content_view_id: string;
  filter_type: FilterType;
  pattern: string;
  created_at: string;
}

export interface ListContentViewsParams {
  limit?: number;
  offset?: number;
}

export function listContentViews(params: ListContentViewsParams = {}): Promise<ContentViewRead[]> {
  return api.get<ContentViewRead[]>("/content-views", params);
}

export function getContentView(contentViewId: string): Promise<ContentViewRead> {
  return api.get<ContentViewRead>(`/content-views/${contentViewId}`);
}

// Cuts version 1 immediately, from the member repositories' current
// package state, in the same request — matches Satellite, where a newly
// created content view already has an initial version.
export function createContentView(payload: ContentViewCreate): Promise<ContentViewRead> {
  return api.post<ContentViewRead>("/content-views", payload);
}

export function deleteContentView(contentViewId: string): Promise<void> {
  return api.delete<void>(`/content-views/${contentViewId}`);
}

export function listContentViewVersions(
  contentViewId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ContentViewVersionRead[]> {
  return api.get<ContentViewVersionRead[]>(`/content-views/${contentViewId}/versions`, params);
}

export function listContentViewFilters(contentViewId: string): Promise<ContentViewFilterRead[]> {
  return api.get<ContentViewFilterRead[]>(`/content-views/${contentViewId}/filters`);
}

export function createContentViewFilter(
  contentViewId: string,
  payload: ContentViewFilterCreate,
): Promise<ContentViewFilterRead> {
  return api.post<ContentViewFilterRead>(`/content-views/${contentViewId}/filters`, payload);
}

export function deleteContentViewFilter(contentViewId: string, filterId: string): Promise<void> {
  return api.delete<void>(`/content-views/${contentViewId}/filters/${filterId}`);
}

// force=true always cuts a new version, even with nothing changed since
// the latest one — a version is also a promotion checkpoint, not purely
// a content-change record.
export function publishContentView(contentViewId: string, force = false): Promise<PublishResponse> {
  return api.post<PublishResponse>(`/content-views/${contentViewId}/publish`, { force });
}
