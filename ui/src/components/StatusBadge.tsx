import { Badge, type BadgeProps } from "@/components/ui/badge";
import { titleCase } from "@/lib/format";

const VARIANT_BY_VALUE: Record<string, NonNullable<BadgeProps["variant"]>> = {
  // ServerStatus
  registered: "secondary",
  bootstrapped: "success",
  unreachable: "destructive",
  // ServerLifecycleState
  active: "success",
  decommissioned: "secondary",
  // JobStatus
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  // RelaySyncStatus
  never_synced: "secondary",
  healthy: "success",
  stale: "warning",
  // Drift status
  outdated: "warning",
  up_to_date: "success",
  not_in_environment: "secondary",
};

export function StatusBadge({ value }: { value: string }) {
  return <Badge variant={VARIANT_BY_VALUE[value] ?? "outline"}>{titleCase(value)}</Badge>;
}
