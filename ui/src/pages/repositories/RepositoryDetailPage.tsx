import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
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
import { getRepository, syncRepository, updateRepository, deleteRepository } from "@/api/repositories";
import { getJob, listJobs } from "@/api/jobs";
import { formatDateTime, formatBytes } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

export function RepositoryDetailPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editArchiveUrl, setEditArchiveUrl] = useState("");
  const [editDistribution, setEditDistribution] = useState("");
  const [editComponents, setEditComponents] = useState("");
  const [editArchitectures, setEditArchitectures] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  if (!name) return null;

  const repoQuery = useQuery({ queryKey: ["repository", name], queryFn: () => getRepository(name) });

  // The current/most recent sync job — polled live while it's still
  // pending/running so this page reflects an in-progress sync without a
  // manual refresh, same pattern as JobDetailPage itself.
  const currentJobId = repoQuery.data?.last_sync_job_id ?? null;
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
    onSuccess: () => {
      toast.success("Sync triggered");
      void queryClient.invalidateQueries({ queryKey: ["repository", name] });
      void queryClient.invalidateQueries({ queryKey: ["jobs", "repository"] });
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
    onSuccess: () => {
      toast.success("Repository updated — sync again to pull from the new source");
      void queryClient.invalidateQueries({ queryKey: ["repository", name] });
      setEditOpen(false);
    },
    onError: (err) => setEditError(errorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRepository(name),
    onSuccess: () => {
      toast.success("Repository deleted");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
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
            </div>

            {currentJob && (
              <div className="mb-6 rounded-lg border p-4">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium">
                    {syncInProgress ? "Sync in progress" : "Last sync"}
                  </p>
                  <div className="flex items-center gap-2">
                    <StatusBadge value={currentJob.status} />
                    <Link to={`/jobs/${currentJob.id}`} className="text-sm text-muted-foreground hover:underline">
                      view job
                    </Link>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                  <span>Started: {formatDateTime(currentJob.started_at)}</span>
                  <span>Finished: {formatDateTime(currentJob.finished_at)}</span>
                </div>
                {currentJob.log_output && (
                  <div className="log-viewer mt-3 max-h-40 overflow-y-auto rounded-md bg-muted p-3 text-xs">
                    {currentJob.log_output}
                  </div>
                )}
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
