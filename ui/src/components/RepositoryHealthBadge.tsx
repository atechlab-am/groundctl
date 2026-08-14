import { Badge } from "@/components/ui/badge";
import type { RepositoryRead } from "@/api/repositories";

const HEALTH_LABEL: Record<RepositoryRead["health_status"], string> = {
  healthy: "Healthy",
  stale: "Stale",
  never_synced: "Never synced",
};

const HEALTH_VARIANT: Record<RepositoryRead["health_status"], "success" | "warning" | "secondary"> = {
  healthy: "success",
  stale: "warning",
  never_synced: "secondary",
};

export function RepositoryHealthBadge({ status }: { status: RepositoryRead["health_status"] }) {
  return <Badge variant={HEALTH_VARIANT[status]}>{HEALTH_LABEL[status]}</Badge>;
}
