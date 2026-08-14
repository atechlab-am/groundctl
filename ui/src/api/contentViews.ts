import { api } from "./client";

// NOTE: the backend has no GET /content-views (list) or GET
// /content-views/{id} (detail) endpoint — confirmed by reading
// app/routers/content_views.py in full. Content views can only be
// created and then referenced by id (e.g. from
// LifecycleEnvironmentRead.content_view_id). The Content Views page
// therefore works from a client-accumulated set (see
// pages/content-views/useKnownContentViews.ts) rather than a real list
// call. This is a backend gap, not something to paper over with an
// invented endpoint.

export type FilterType = "include" | "exclude" | "errata_since";

export interface ContentViewCreate {
  name: string;
  repository_ids: string[];
}

export interface ContentViewRead {
  id: string;
  name: string;
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

export function createContentView(payload: ContentViewCreate): Promise<ContentViewRead> {
  return api.post<ContentViewRead>("/content-views", payload);
}

export function listContentViewVersions(
  contentViewId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ContentViewVersionRead[]> {
  return api.get<ContentViewVersionRead[]>(`/content-views/${contentViewId}/versions`, params);
}

export function createContentViewFilter(
  contentViewId: string,
  payload: ContentViewFilterCreate,
): Promise<ContentViewFilterRead> {
  return api.post<ContentViewFilterRead>(`/content-views/${contentViewId}/filters`, payload);
}

export function publishContentView(contentViewId: string): Promise<PublishResponse> {
  return api.post<PublishResponse>(`/content-views/${contentViewId}/publish`);
}
