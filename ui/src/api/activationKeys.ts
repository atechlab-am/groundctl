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

// Same-origin URL (see CLAUDE.md's Frontend section — the SPA is served by
// the same FastAPI app as the API, no separate origin to configure) to the
// generated enrollment script — GET /api/enrollment/script?token=... itself
// needs no auth beyond the token (see app/routers/enrollment.py), so this
// is a plain URL to hand to the operator, not an api.* call. Every resource
// endpoint is mounted under /api (see client.ts's API_PREFIX) — this must
// stay in sync with that, since it's built independently (a raw curl
// command, not routed through apiRequest/buildUrl).
export function enrollmentScriptCommand(token: string): string {
  const url = new URL("/api/enrollment/script", window.location.origin);
  url.searchParams.set("token", token);
  return `curl -sSL ${url.toString()} | sudo bash`;
}
