import { api } from "./client";

export type ErratumSource = "usn" | "dsa";

export interface ErratumPackageRead {
  release: string;
  package_name: string;
  fixed_version: string;
}

export interface ErratumRead {
  id: string;
  advisory_id: string;
  source: ErratumSource;
  title: string;
  cves: string[];
  severity: string | null;
  published_at: string;
  packages: ErratumPackageRead[];
}

export interface AffectedServer {
  server_id: string;
  hostname: string;
  package_name: string;
  installed_version: string;
  fixed_version: string;
}

export interface AffectedServersResponse {
  advisory_id: string;
  affected: AffectedServer[];
}

export interface ListErrataParams {
  source?: ErratumSource;
  cve?: string;
  published_since?: string;
  limit?: number;
  offset?: number;
}

export function listErrata(params: ListErrataParams = {}): Promise<ErratumRead[]> {
  return api.get<ErratumRead[]>("/errata", params);
}

export function getErratum(advisoryId: string): Promise<ErratumRead> {
  return api.get<ErratumRead>(`/errata/${encodeURIComponent(advisoryId)}`);
}

export function getAffectedServers(advisoryId: string): Promise<AffectedServersResponse> {
  return api.get<AffectedServersResponse>(`/errata/${encodeURIComponent(advisoryId)}/affected-servers`);
}
