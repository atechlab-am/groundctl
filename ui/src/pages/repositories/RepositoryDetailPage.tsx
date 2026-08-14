import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { JobStatusIndicator } from "@/components/JobStatusIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RoleGate } from "@/layout/RoleGate";
import { useHasRole } from "@/auth/useHasRole";
import { Checkbox } from "@/components/ui/checkbox";
import {
  getRepository,
  syncRepository,
  updateRepository,
  updateRepositoryAutoSync,
  deleteRepository,
} from "@/api/repositories";
import { getJob, listJobs } from "@/api/jobs";
import { formatDateTime, formatBytes } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

export function RepositoryDetailPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canOperate = useHasRole("operator");
  const [editOpen, setEditOpen] = useState(false);
  const [editArchiveUrl, setEditArchiveUrl] = useState("");
  const [editDistribution, setEditDistribution] = useState("");
  const [editComponents, setEditComponents] = useState("");
  const [editArchitectures, setEditArchitectures] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  // Set by Sync/Edit/Delete's own onSuccess — takes priority over
  // last_sync_job_id, which only ever tracks Sync (Edit isn't recorded on
  // the row at all, and Delete's Job outlives the Repository row it
  // targeted).
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  if (!name) return null;

  const repoQuery = useQuery({ queryKey: ["repository", name], queryFn: () => getRepository(name) });

  // Polled live while pending/running so this page reflects an
  // in-progress job without a manual refresh, same pattern as
  // JobDetailPage itself. last_job_id (tracks Sync/Edit/Delete alike)
  // takes priority over the narrower last_sync_job_id so a reload during
  // an Edit or Delete still recovers live status, not just Sync.
  const currentJobId = activeJobId ?? repoQuery.data?.last_job_id ?? repoQuery.data?.last_sync_job_id ?? null;
  const currentJobQuery = useQuery({
    queryKey: ["job", currentJobId],
    queryFn: () => getJob(currentJobId!),
    enabled: currentJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  const jobsQuery = useQuery({
    queryKey: ["jobs", "repository", repoQuery.data?.id],
    queryFn: () => listJobs({ repository_id: repoQuery.data!.id, limit: 50 }),
    enabled: repoQuery.data !== undefined,
  });

  const syncMutation = useMutation({
    mutationFn: () => syncRepository(name),
    onSuccess: (job) => {
      toast.success("Sync triggered");
      setActiveJobId(job.id);
      void queryClient.invalidateQueries({ queryKey: ["repository", name] });
      void queryClient.invalidateQueries({ queryKey: ["jobs", "repository"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const autoSyncMutation = useMutation({
    mutationFn: (enabled: boolean) => updateRepositoryAutoSync(name, enabled),
    onSuccess: (_repo, enabled) => {
      toast.success(enabled ? "Nightly auto-sync enabled" : "Nightly auto-sync disabled");
      void queryClient.invalidateQueries({ queryKey: ["repository", name] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function openEdit() {
    if (!repoQuery.data) return;
    setEditArchiveUrl(repoQuery.data.archive_url);
    setEditDistribution(repoQuery.data.distribution);
    setEditComponents(repoQuery.data.components.join(","));
    setEditArchitectures(repoQuery.data.architectures.join(","));
    setEditError(null);
    setEditOpen(true);
  }

  const updateMutation = useMutation({
    mutationFn: () =>
      updateRepository(name, {
        archive_url: editArchiveUrl,
        distribution: editDistribution,
        components: editComponents.split(",").map((s) => s.trim()).filter(Boolean),
        architectures: editArchitectures.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: (job) => {
      toast.success("Update triggered");
      setActiveJobId(job.id);
      void queryClient.invalidateQueries({ queryKey: ["repository", name] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setEditOpen(false);
    },
    onError: (err) => setEditError(errorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRepository(name),
    onSuccess: () => {
      toast.success("Delete triggered — check the Jobs page for progress");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate("/repositories");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleDelete() {
    if (!confirm(`Delete repository "${name}"? This removes the aptly mirror and cannot be undone.`)) return;
    deleteMutation.mutate();
  }

  const repo = repoQuery.data;
  const currentJob = currentJobQuery.data;
  const syncInProgress = currentJob?.status === "pending" || currentJob?.status === "running";

  // "Usually takes ~Xm" — average duration of this repo's own past
  // successful jobs of the SAME type as the one currently running.
  // Aptly gives no progress signal for sync/edit/delete (single blocking
  // call, confirmed repeatedly), so a real percentage/ETA isn't
  // buildable — this is the honest substitute: real history, not a
  // guess. Computed from jobsQuery, already fetched for the sync-history
  // list below, so this costs nothing extra.
  const typicalDuration = (() => {
    if (!currentJob || !jobsQuery.data) return null;
    const durationsMs = jobsQuery.data
      .filter(
        (j) =>
          j.job_type === currentJob.job_type &&
          j.status === "success" &&
          j.id !== currentJob.id &&
          j.started_at &&
          j.finished_at,
      )
      .map((j) => new Date(j.finished_at!).getTime() - new Date(j.started_at!).getTime());
    if (durationsMs.length === 0) return null;
    const avgMs = durationsMs.reduce((sum, ms) => sum + ms, 0) / durationsMs.length;
    const avgMinutes = Math.round(avgMs / 60000);
    if (avgMinutes < 1) return "under a minute";
    if (avgMinutes < 60) return `${avgMinutes}m`;
    const hours = Math.floor(avgMinutes / 60);
    return `${hours}h ${avgMinutes % 60}m`;
  })();

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/repositories")}>
        <ArrowLeft className="h-4 w-4" />
        Back to repositories
      </Button>

      <QueryState isLoading={repoQuery.isLoading} isError={repoQuery.isError} error={repoQuery.error}>
        {repo && (
          <>
            <PageHeader
              title={repo.name}
              description={repo.archive_url}
              actions={
                <RoleGate minRole="operator">
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={syncMutation.isPending || syncInProgress}
                      onClick={() => syncMutation.mutate()}
                    >
                      <RefreshCw className="h-4 w-4" />
                      {syncInProgress ? "Syncing…" : "Sync"}
                    </Button>
                    <Button variant="outline" size="sm" onClick={openEdit}>
                      <Pencil className="h-4 w-4" />
                      Edit
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={deleteMutation.isPending}
                      onClick={handleDelete}
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </Button>
                  </div>
                </RoleGate>
              }
            />

            <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <InfoItem label="Distribution" value={repo.distribution} />
              <InfoItem
                label="Components"
                value={
                  <div className="flex flex-wrap gap-1">
                    {repo.components.map((c) => (
                      <Badge key={c} variant="outline">
                        {c}
                      </Badge>
                    ))}
                  </div>
                }
              />
              <InfoItem label="Architectures" value={repo.architectures.join(", ")} />
              <InfoItem label="Size" value={formatBytes(repo.size_bytes)} />
              <InfoItem label="Created" value={formatDateTime(repo.created_at)} />
              <InfoItem label="Last synced" value={formatDateTime(repo.last_synced_at)} />
              <InfoItem
                label="Nightly auto-sync"
                value={
                  canOperate ? (
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={repo.auto_sync_enabled}
                        disabled={autoSyncMutation.isPending}
                        onCheckedChange={(checked) => autoSyncMutation.mutate(checked === true)}
                        aria-label="Nightly auto-sync"
                      />
                      <span className="text-sm font-normal text-muted-foreground">
                        {repo.auto_sync_enabled ? "On" : "Off"}
                      </span>
                    </div>
                  ) : repo.auto_sync_enabled ? (
                    "On"
                  ) : (
                    "Off"
                  )
                }
              />
            </div>

            {currentJob && currentJobId && (
              <div className="mb-6 rounded-lg border p-4">
                <p className="mb-2 text-sm font-medium">{syncInProgress ? "Job in progress" : "Last job"}</p>
                <JobStatusIndicator jobId={currentJobId} />
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                  <span>Started: {formatDateTime(currentJob.started_at)}</span>
                  <span>Finished: {formatDateTime(currentJob.finished_at)}</span>
                  {syncInProgress && typicalDuration !== null && (
                    <span>Usually takes: ~{typicalDuration}</span>
                  )}
                </div>
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-medium">Sync history</p>
              <QueryState
                isLoading={jobsQuery.isLoading}
                isError={jobsQuery.isError}
                error={jobsQuery.error}
                isEmpty={jobsQuery.data?.length === 0}
                emptyMessage="No syncs yet."
              >
                <ul className="flex flex-col divide-y rounded-lg border">
                  {jobsQuery.data?.map((job) => (
                    <li key={job.id} className="flex items-center justify-between px-4 py-2 text-sm">
                      <Link to={`/jobs/${job.id}`} className="font-medium hover:underline">
                        {formatDateTime(job.created_at)}
                      </Link>
                      <StatusBadge value={job.status} />
                    </li>
                  ))}
                </ul>
              </QueryState>
            </div>
          </>
        )}
      </QueryState>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setEditError(null);
              updateMutation.mutate();
            }}
          >
            <DialogHeader>
              <DialogTitle>Edit {name}</DialogTitle>
              <DialogDescription>
                Aptly can't change a mirror's source in place — saving deletes the old mirror and creates a new one
                with these settings. Size and last-synced reset; sync again afterward to pull from the new source.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-4">
              {editError && <p className="text-sm text-destructive">{editError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-archive-url">Archive URL</Label>
                <Input
                  id="edit-archive-url"
                  type="url"
                  value={editArchiveUrl}
                  onChange={(e) => setEditArchiveUrl(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-distribution">Distribution</Label>
                <Input
                  id="edit-distribution"
                  value={editDistribution}
                  onChange={(e) => setEditDistribution(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-components">Components (comma-separated)</Label>
                <Input
                  id="edit-components"
                  value={editComponents}
                  onChange={(e) => setEditComponents(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-architectures">Architectures (comma-separated)</Label>
                <Input
                  id="edit-architectures"
                  value={editArchitectures}
                  onChange={(e) => setEditArchitectures(e.target.value)}
                  required
                />
              </div>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  );
}
