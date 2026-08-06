import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogs, downloadAuditLogsCsv, type AuditAction } from "@/api/auditLogs";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, titleCase } from "@/lib/format";

const AUDIT_ACTIONS: AuditAction[] = [
  "create_user",
  "create_repository",
  "sync_repository",
  "cut_snapshot",
  "publish_content_view",
  "switch_publish",
  "rollback_environment",
  "create_content_view",
  "create_content_view_filter",
  "create_lifecycle_environment",
  "create_server",
  "trigger_bootstrap",
  "trigger_apply_updates",
  "trigger_gather_facts",
  "create_host_group",
  "update_host_group_membership",
  "create_activation_key",
  "revoke_activation_key",
  "register_via_activation_key",
  "trigger_bulk_apply_updates",
  "trigger_run_command",
  "trigger_manage_package",
  "decommission_server",
  "mark_server_unreachable",
  "flag_stale_server",
  "create_site",
  "create_relay",
  "update_site_environments",
  "assign_server_site",
  "login",
  "login_failed",
  "export_audit_log",
  "update_user",
  "deactivate_user",
  "reactivate_user",
  "change_own_password",
  "update_branding",
];

export function AuditLogsPage() {
  const [userId, setUserId] = useState("");
  const [action, setAction] = useState<AuditAction | "all">("all");
  const [resourceType, setResourceType] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const filters = {
    user_id: userId || undefined,
    action: action === "all" ? undefined : action,
    resource_type: resourceType || undefined,
    since: since ? new Date(since).toISOString() : undefined,
    until: until ? new Date(until).toISOString() : undefined,
  };

  const logsQuery = useQuery({
    queryKey: ["audit-logs", filters],
    queryFn: () => listAuditLogs({ ...filters, limit: 200 }),
  });

  const exportMutation = useMutation({
    mutationFn: () => downloadAuditLogsCsv(filters),
    onSuccess: () => toast.success("Export downloaded"),
    onError: (err) => toast.error(errorMessage(err)),
  });

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        description="Who did what — admin only"
        actions={
          <Button size="sm" variant="outline" disabled={exportMutation.isPending} onClick={() => exportMutation.mutate()}>
            <Download className="h-4 w-4" />
            {exportMutation.isPending ? "Exporting…" : "Export CSV"}
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="al-user">User ID</Label>
          <Input id="al-user" value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="uuid" className="w-48" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Action</Label>
          <Select value={action} onValueChange={(v) => setAction(v as AuditAction | "all")}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">All actions</SelectItem>
              {AUDIT_ACTIONS.map((a) => (
                <SelectItem key={a} value={a}>
                  {titleCase(a)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="al-resource">Resource type</Label>
          <Input
            id="al-resource"
            value={resourceType}
            onChange={(e) => setResourceType(e.target.value)}
            placeholder="server"
            className="w-40"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="al-since">Since</Label>
          <Input id="al-since" type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} className="w-52" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="al-until">Until</Label>
          <Input id="al-until" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} className="w-52" />
        </div>
      </div>

      <QueryState
        isLoading={logsQuery.isLoading}
        isError={logsQuery.isError}
        error={logsQuery.error}
        isEmpty={logsQuery.data?.length === 0}
        emptyMessage="No audit log entries match these filters."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logsQuery.data?.map((log) => (
              <TableRow key={log.id}>
                <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(log.created_at)}</TableCell>
                <TableCell className="font-medium">{titleCase(log.action)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {log.resource_type}
                  {log.resource_id ? ` / ${log.resource_id.slice(0, 8)}` : ""}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {log.user_id ? log.user_id.slice(0, 8) : "system"}
                </TableCell>
                <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                  {log.detail ? JSON.stringify(log.detail) : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
