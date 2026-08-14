import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import { ArrowUpCircle, ExternalLink, RefreshCw, ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { QueryState } from "@/components/QueryState";
import { useHasRole } from "@/auth/useHasRole";
import { getVersion, checkVersionNow, getChangelog } from "@/api/version";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

const GITHUB_REPO_URL = "https://github.com/atechlab-am/groundctl";

// Refetches hourly, not on every mount — the underlying check itself only
// runs once a day server-side (scheduled_check_for_new_version), so
// anything more frequent than that would just be re-reading the same
// cached row. checkVersionNow (admin, manual) bypasses this entirely.
const REFETCH_INTERVAL_MS = 60 * 60 * 1000;

export function VersionNotice() {
  const queryClient = useQueryClient();
  const isAdmin = useHasRole("admin");
  const [changelogOpen, setChangelogOpen] = useState(false);

  const versionQuery = useQuery({
    queryKey: ["version"],
    queryFn: getVersion,
    refetchInterval: REFETCH_INTERVAL_MS,
    // A version check is the definition of non-critical — never worth a
    // retry storm or a console error a user would notice.
    retry: false,
  });

  const checkNowMutation = useMutation({
    mutationFn: checkVersionNow,
    onSuccess: (result) => {
      queryClient.setQueryData(["version"], result);
      toast.success(
        result.update_available && result.latest_version
          ? `Update available: v${result.latest_version}`
          : "You're on the latest version",
      );
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const changelogQuery = useQuery({
    queryKey: ["changelog"],
    queryFn: getChangelog,
    enabled: changelogOpen,
    staleTime: 5 * 60 * 1000,
  });

  if (!versionQuery.data) return <div />;

  const { current_version, latest_version, update_available, last_checked_at } = versionQuery.data;

  return (
    <>
      <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <span>v{current_version}</span>

        {update_available && latest_version && (
          <a
            href={`${GITHUB_REPO_URL}/releases/tag/v${latest_version}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex"
          >
            <Badge variant="success" className="gap-1 hover:opacity-90">
              <ArrowUpCircle className="h-3 w-3" />v{latest_version} available
            </Badge>
          </a>
        )}

        <Button
          variant="ghost"
          size="sm"
          className="h-6 gap-1 px-1.5 text-xs text-muted-foreground"
          onClick={() => setChangelogOpen(true)}
        >
          <ScrollText className="h-3 w-3" />
          Changelog
        </Button>

        <a href={GITHUB_REPO_URL} target="_blank" rel="noreferrer" className="inline-flex">
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-1.5 text-xs text-muted-foreground">
            <ExternalLink className="h-3 w-3" />
            GitHub
          </Button>
        </a>

        {isAdmin && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-1.5 text-xs text-muted-foreground"
            title={last_checked_at ? `Last checked ${formatDateTime(last_checked_at)}` : "Never checked"}
            disabled={checkNowMutation.isPending}
            onClick={() => checkNowMutation.mutate()}
          >
            <RefreshCw className={`h-3 w-3 ${checkNowMutation.isPending ? "animate-spin" : ""}`} />
            {checkNowMutation.isPending ? "Checking…" : "Check now"}
          </Button>
        )}
      </div>

      <Dialog open={changelogOpen} onOpenChange={setChangelogOpen}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader className="flex-row items-center justify-between">
            <DialogTitle>Changelog</DialogTitle>
            <a
              href={`${GITHUB_REPO_URL}/blob/main/CHANGELOG.md`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
            >
              View on GitHub
              <ExternalLink className="h-3 w-3" />
            </a>
          </DialogHeader>
          <QueryState
            isLoading={changelogQuery.isLoading}
            isError={changelogQuery.isError}
            error={changelogQuery.error}
          >
            {changelogQuery.data && (
              <article className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{changelogQuery.data.content}</ReactMarkdown>
              </article>
            )}
          </QueryState>
        </DialogContent>
      </Dialog>
    </>
  );
}
