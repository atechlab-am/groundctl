import { api, apiRequestRaw } from "./client";

export type AuditAction =
  | "create_user"
  | "create_repository"
  | "sync_repository"
  | "cut_snapshot"
  | "publish_content_view"
  | "switch_publish"
  | "rollback_environment"
  | "create_content_view"
  | "create_content_view_filter"
  | "create_lifecycle_environment"
  | "create_server"
  | "trigger_bootstrap"
  | "trigger_apply_updates"
  | "trigger_gather_facts"
  | "create_host_group"
  | "update_host_group_membership"
  | "create_activation_key"
  | "revoke_activation_key"
  | "register_via_activation_key"
  | "trigger_bulk_apply_updates"
  | "trigger_run_command"
  | "trigger_manage_package"
  | "decommission_server"
  | "mark_server_unreachable"
  | "flag_stale_server"
  | "create_site"
  | "create_relay"
  | "update_site_environments"
  | "assign_server_site"
  | "login"
  | "login_failed"
  | "export_audit_log";

export interface AuditLogRead {
  id: string;
  user_id: string | null;
  action: AuditAction;
  resource_type: string;
  resource_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogFilterParams {
  user_id?: string;
  action?: AuditAction;
  resource_type?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export function listAuditLogs(params: AuditLogFilterParams = {}): Promise<AuditLogRead[]> {
  return api.get<AuditLogRead[]>("/audit-logs", params);
}

// GET /audit-logs/export requires Bearer auth (admin-only), so a plain
// <a href> can't carry the Authorization header. Fetch as a blob and
// trigger a real browser download via a temporary object URL, applying
// whatever filters are currently active on the audit log screen.
export async function downloadAuditLogsCsv(
  params: Omit<AuditLogFilterParams, "limit" | "offset"> = {},
): Promise<void> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  const response = await apiRequestRaw(`/audit-logs/export${qs ? `?${qs}` : ""}`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = "audit-log-export.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
