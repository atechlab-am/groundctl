import { api } from "./client";

export interface InstanceSettingsRead {
  audit_log_retention_days: number;
  activation_key_default_ttl_hours: number;
  stale_checkin_hours: number;
  relay_stale_threshold_hours: number;
  // Display-only threshold for RepositoryRead.health_status — unlike the
  // two above, doesn't drive a scheduled sweep or webhook.
  repository_stale_threshold_hours: number;
  disk_usage_warn_percent: number;
  webhook_url: string | null;
  // webhook_secret itself is never returned by the API (write-only, same
  // posture as a password) — this only says whether one is set.
  has_webhook_secret: boolean;
  // Per field, whether the value shown is a DB override or the env-var
  // default it otherwise falls back to.
  overridden: Record<string, boolean>;
  updated_at: string | null;
}

// null clears an override back to the env-var default; omitted (undefined)
// leaves the field unchanged; a value sets an override. webhook_secret:
// null actually erases a previously-set secret, not just "use the env var".
export interface InstanceSettingsUpdate {
  audit_log_retention_days?: number | null;
  activation_key_default_ttl_hours?: number | null;
  stale_checkin_hours?: number | null;
  relay_stale_threshold_hours?: number | null;
  repository_stale_threshold_hours?: number | null;
  disk_usage_warn_percent?: number | null;
  webhook_url?: string | null;
  webhook_secret?: string | null;
}

export function getInstanceSettings(): Promise<InstanceSettingsRead> {
  return api.get<InstanceSettingsRead>("/instance-settings");
}

export function updateInstanceSettings(payload: InstanceSettingsUpdate): Promise<InstanceSettingsRead> {
  return api.put<InstanceSettingsRead>("/instance-settings", payload);
}
