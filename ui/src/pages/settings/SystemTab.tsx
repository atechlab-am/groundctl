import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RotateCcw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { QueryState } from "@/components/QueryState";
import { getInstanceSettings, updateInstanceSettings } from "@/api/instance-settings";
import { errorMessage } from "@/lib/errors";

type NumericField =
  | "audit_log_retention_days"
  | "activation_key_default_ttl_hours"
  | "stale_checkin_hours"
  | "relay_stale_threshold_hours"
  | "disk_usage_warn_percent";

const NUMERIC_FIELDS: { key: NumericField; label: string; help: string; step?: string }[] = [
  {
    key: "audit_log_retention_days",
    label: "Audit log retention (days)",
    help: "Audit log rows older than this are purged by the nightly retention sweep.",
  },
  {
    key: "activation_key_default_ttl_hours",
    label: "Activation key default TTL (hours)",
    help: "Applied when an activation key is created without an explicit expiry.",
  },
  {
    key: "stale_checkin_hours",
    label: "Stale server threshold (hours)",
    help: "A server with no groundctl-triggered activity in this long is flagged stale.",
  },
  {
    key: "relay_stale_threshold_hours",
    label: "Stale relay threshold (hours)",
    help: "A relay whose last sync exceeds this is flagged stale and job routing falls back to the primary.",
  },
  {
    key: "disk_usage_warn_percent",
    label: "Disk usage warning threshold (%)",
    help: "Fires a disk.usage_high webhook when aptly's data volume crosses this percent used.",
    step: "0.1",
  },
];

export function SystemTab() {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<NumericField, string>>({
    audit_log_retention_days: "",
    activation_key_default_ttl_hours: "",
    stale_checkin_hours: "",
    relay_stale_threshold_hours: "",
    disk_usage_warn_percent: "",
  });
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [error, setError] = useState<string | null>(null);

  const settingsQuery = useQuery({ queryKey: ["instance-settings"], queryFn: getInstanceSettings });

  useEffect(() => {
    if (!settingsQuery.data) return;
    const data = settingsQuery.data;
    setValues({
      audit_log_retention_days: String(data.audit_log_retention_days),
      activation_key_default_ttl_hours: String(data.activation_key_default_ttl_hours),
      stale_checkin_hours: String(data.stale_checkin_hours),
      relay_stale_threshold_hours: String(data.relay_stale_threshold_hours),
      disk_usage_warn_percent: String(data.disk_usage_warn_percent),
    });
    setWebhookUrl(data.webhook_url ?? "");
  }, [settingsQuery.data]);

  const updateMutation = useMutation({
    mutationFn: updateInstanceSettings,
    onSuccess: () => {
      toast.success("Settings updated");
      void queryClient.invalidateQueries({ queryKey: ["instance-settings"] });
      setWebhookSecret("");
      setError(null);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  function handleSaveNumeric(field: NumericField) {
    setError(null);
    const raw = values[field];
    const parsed = Number(raw);
    if (raw.trim() === "" || Number.isNaN(parsed)) {
      setError("Enter a valid number.");
      return;
    }
    updateMutation.mutate({ [field]: parsed });
  }

  function handleResetNumeric(field: NumericField) {
    setError(null);
    updateMutation.mutate({ [field]: null });
  }

  function handleSaveWebhook() {
    setError(null);
    updateMutation.mutate({
      webhook_url: webhookUrl.trim() === "" ? null : webhookUrl.trim(),
      ...(webhookSecret.trim() !== "" ? { webhook_secret: webhookSecret.trim() } : {}),
    });
  }

  function handleClearWebhookSecret() {
    setError(null);
    updateMutation.mutate({ webhook_secret: null });
  }

  return (
    <QueryState isLoading={settingsQuery.isLoading} isError={settingsQuery.isError} error={settingsQuery.error}>
      <div className="flex flex-col gap-6">
        {error && <p className="text-sm text-destructive">{error}</p>}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Operational thresholds</CardTitle>
            <CardDescription>
              Override the built-in defaults. "Default" means no override is set — the value shown is what
              config.py/the environment provides.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {NUMERIC_FIELDS.map((field) => (
              <div key={field.key} className="flex flex-col gap-1.5 border-b pb-4 last:border-b-0 last:pb-0">
                <div className="flex items-center gap-2">
                  <Label htmlFor={field.key}>{field.label}</Label>
                  {settingsQuery.data && !settingsQuery.data.overridden[field.key] && (
                    <Badge variant="outline" className="text-xs">
                      default
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{field.help}</p>
                <div className="flex items-center gap-2">
                  <Input
                    id={field.key}
                    type="number"
                    step={field.step}
                    value={values[field.key]}
                    onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                    className="w-40"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={updateMutation.isPending}
                    onClick={() => handleSaveNumeric(field.key)}
                  >
                    Save
                  </Button>
                  {settingsQuery.data?.overridden[field.key] && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={updateMutation.isPending}
                      onClick={() => handleResetNumeric(field.key)}
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Reset to default
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Webhook alerting</CardTitle>
            <CardDescription>
              Fire-and-forget delivery for server.stale, server.unreachable, relay.stale, relay.sync_failed, and
              disk.usage_high events. Leave the URL empty to disable delivery.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="webhook-url">Webhook URL</Label>
              <Input
                id="webhook-url"
                type="url"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://example.com/hooks/groundctl"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="webhook-secret">
                Signing secret{" "}
                {settingsQuery.data?.has_webhook_secret && (
                  <span className="text-xs font-normal text-muted-foreground">(currently set)</span>
                )}
              </Label>
              <Input
                id="webhook-secret"
                type="password"
                value={webhookSecret}
                onChange={(e) => setWebhookSecret(e.target.value)}
                placeholder={settingsQuery.data?.has_webhook_secret ? "Leave blank to keep current secret" : "Optional"}
              />
              <p className="text-xs text-muted-foreground">
                Signs delivered payloads with HMAC-SHA256 (X-Groundctl-Signature). Never shown again once saved.
              </p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" disabled={updateMutation.isPending} onClick={handleSaveWebhook}>
                {updateMutation.isPending ? "Saving…" : "Save"}
              </Button>
              {settingsQuery.data?.has_webhook_secret && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={updateMutation.isPending}
                  onClick={handleClearWebhookSecret}
                >
                  Clear secret
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </QueryState>
  );
}
