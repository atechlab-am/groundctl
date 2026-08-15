import { api } from "./client";

export type JobType =
  | "bootstrap"
  | "apply_updates"
  | "gather_facts"
  | "bulk_apply_updates"
  | "run_command"
  | "manage_package"
  | "sync_repository"
  | "update_repository"
  | "delete_repository"
  | "install_beacon";

export type JobStatus = "pending" | "running" | "success" | "failed";
export type JobTargetType = "server" | "environment" | "host_group" | "adhoc" | "repository";
export type PackageAction = "install" | "remove";

export interface JobRead {
  id: string;
  job_type: JobType;
  status: JobStatus;
  target_type: JobTargetType;
  server_id: string | null;
  environment_id: string | null;
  host_group_id: string | null;
  repository_id: string | null;
  server_ids: string[];
  log_output: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface BulkTargetSelector {
  host_group_id?: string | null;
  server_ids?: string[] | null;
}

export type BulkApplyUpdatesRequest = BulkTargetSelector;

export interface RunCommandRequest extends BulkTargetSelector {
  command: string;
}

export interface ManagePackageRequest {
  server_id: string;
  package_name: string;
  action: PackageAction;
}

export interface ListJobsParams {
  job_type?: JobType;
  status?: JobStatus;
  environment_id?: string;
  server_id?: string;
  repository_id?: string;
  limit?: number;
  offset?: number;
}

export function listJobs(params: ListJobsParams = {}): Promise<JobRead[]> {
  return api.get<JobRead[]>("/jobs", params);
}

export function getJob(jobId: string): Promise<JobRead> {
  return api.get<JobRead>(`/jobs/${jobId}`);
}

export function triggerBootstrap(serverId: string): Promise<JobRead> {
  return api.post<JobRead>(`/jobs/bootstrap/${serverId}`);
}

// Mints a new BeaconToken server-side and delivers it over the SSH access
// already in place — see api/servers.ts's issueBeaconToken for the
// operator-facing token-mint endpoint used when installing manually instead.
export function triggerInstallBeacon(serverId: string): Promise<JobRead> {
  return api.post<JobRead>(`/jobs/install-beacon/${serverId}`);
}

// environment_id is a query param, not a body field (see
// app/routers/jobs.py's trigger_apply_updates/trigger_gather_facts).
export function triggerApplyUpdates(environmentId: string): Promise<JobRead> {
  return api.post<JobRead>("/jobs/apply-updates", undefined, { environment_id: environmentId });
}

export function triggerGatherFacts(environmentId: string): Promise<JobRead> {
  return api.post<JobRead>("/jobs/gather-facts", undefined, { environment_id: environmentId });
}

export function triggerBulkApplyUpdates(payload: BulkApplyUpdatesRequest): Promise<JobRead> {
  return api.post<JobRead>("/jobs/bulk-apply-updates", payload);
}

// Admin-only server-side (require_role(Role.admin)) — UI must hide this
// entirely for non-admins, not just disable it.
export function triggerRunCommand(payload: RunCommandRequest): Promise<JobRead> {
  return api.post<JobRead>("/jobs/run-command", payload);
}

export function triggerManagePackage(payload: ManagePackageRequest): Promise<JobRead> {
  return api.post<JobRead>("/jobs/manage-package", payload);
}

export function cancelJob(jobId: string): Promise<JobRead> {
  return api.post<JobRead>(`/jobs/${jobId}/cancel`);
}
