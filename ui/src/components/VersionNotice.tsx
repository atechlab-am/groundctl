import { useQuery } from "@tanstack/react-query";
import { ArrowUpCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getVersion } from "@/api/version";

// Refetches hourly, not on every mount — the underlying check itself only
// runs once a day server-side (scheduled_check_for_new_version), so
// anything more frequent than that would just be re-reading the same
// cached row.
const REFETCH_INTERVAL_MS = 60 * 60 * 1000;

export function VersionNotice() {
  const versionQuery = useQuery({
    queryKey: ["version"],
    queryFn: getVersion,
    refetchInterval: REFETCH_INTERVAL_MS,
    // A version check is the definition of non-critical — never worth a
    // retry storm or a console error a user would notice.
    retry: false,
  });

  if (!versionQuery.data) return <div />;

  const { current_version, latest_version, update_available } = versionQuery.data;

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span>v{current_version}</span>
      {update_available && latest_version && (
        <a
          href={`https://github.com/atechlab-am/groundctl/releases/tag/v${latest_version}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex"
        >
          <Badge variant="success" className="gap-1 hover:opacity-90">
            <ArrowUpCircle className="h-3 w-3" />v{latest_version} available
          </Badge>
        </a>
      )}
    </div>
  );
}
