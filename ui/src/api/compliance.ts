import { api } from "./client";

export type DriftStatus = "outdated" | "up_to_date" | "not_in_environment";
export type VersionComparator = "lt" | "le" | "eq" | "ge" | "gt";

export interface PackageDrift {
  name: string;
  installed_version: string | null;
  available_version: string | null;
  status: DriftStatus;
}

export interface ComplianceCheckResult {
  server_id: string;
  checked_at: string;
  drift: PackageDrift[];
}

export interface PackageSearchResult {
  server_id: string;
  hostname: string;
  installed_version: string;
}

export interface PackageSearchResponse {
  package_name: string;
  operator: VersionComparator | null;
  compare_version: string | null;
  matches: PackageSearchResult[];
}

export function checkServerCompliance(serverId: string): Promise<ComplianceCheckResult> {
  return api.post<ComplianceCheckResult>(`/compliance/servers/${serverId}/check`);
}

export interface SearchPackagesParams {
  package_name: string;
  operator?: VersionComparator;
  compare_version?: string;
}

export function searchPackages(params: SearchPackagesParams): Promise<PackageSearchResponse> {
  return api.get<PackageSearchResponse>("/compliance/packages/search", params);
}
