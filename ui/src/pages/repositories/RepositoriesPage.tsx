import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { MoreHorizontal, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { RoleGate } from "@/layout/RoleGate";
import {
  listRepositories,
  probeRepositoryArchive,
  createRepositoriesBatch,
  syncRepository,
  estimateRepositorySize,
  updateRepository,
  deleteRepository,
  type RepositoryRead,
} from "@/api/repositories";
import { formatDateTime, formatBytes } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

const DEFAULT_ARCHIVE_URL = "http://archive.ubuntu.com/ubuntu";

export function RepositoriesPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [archiveUrl, setArchiveUrl] = useState(DEFAULT_ARCHIVE_URL);
  const [distributions, setDistributions] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [componentsInput, setComponentsInput] = useState("main,universe");
  const [architecturesInput, setArchitecturesInput] = useState("amd64");
  const [formError, setFormError] = useState<string | null>(null);

  const repositoriesQuery = useQuery({ queryKey: ["repositories"], queryFn: () => listRepositories({ limit: 100 }) });

  function resetDialog() {
    setArchiveUrl(DEFAULT_ARCHIVE_URL);
    setDistributions(null);
    setSelected(new Set());
    setComponentsInput("main,universe");
    setArchitecturesInput("amd64");
    setFormError(null);
    estimateMutation.reset();
  }

  const probeMutation = useMutation({
    mutationFn: (url: string) => probeRepositoryArchive(url),
    onSuccess: (result) => {
      setDistributions(result.distributions);
      setSelected(new Set());
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  // Best-effort — a failed estimate (e.g. one distribution's Packages files
  // 404 for the chosen components/architectures) shouldn't block the
  // operator from creating the repository, so errors are shown inline next
  // to the estimate rather than through formError/toast.
  const estimateMutation = useMutation({
    mutationFn: estimateRepositorySize,
  });

  function handleEstimate(distribution: string) {
    estimateMutation.mutate({
      archive_url: archiveUrl,
      distribution,
      components: componentsInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      architectures: architecturesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
  }

  const createMutation = useMutation({
    mutationFn: createRepositoriesBatch,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      if (result.created.length === 1 && result.created[0]) {
        toast.success(`Repository "${result.created[0].name}" created`);
      } else if (result.created.length > 1) {
        toast.success(`${result.created.length} repositories created`);
      }
      if (result.errors.length > 0) {
        for (const err of result.errors) {
          toast.error(`${err.distribution}: ${err.detail}`);
        }
      }
      if (result.errors.length === 0) {
        setDialogOpen(false);
        resetDialog();
      } else {
        // Leave the dialog open so the user can see which distributions
        // failed and retry just those — successful ones are already
        // created, re-selecting them would just 409.
        setSelected((prev) => {
          const next = new Set(prev);
          for (const created of result.created) next.delete(created.name);
          return next;
        });
      }
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const syncMutation = useMutation({
    mutationFn: (name: string) => syncRepository(name),
    onSuccess: () => {
      toast.success("Sync triggered — click the repository's status to follow progress");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const [editing, setEditing] = useState<RepositoryRead | null>(null);
  const [editArchiveUrl, setEditArchiveUrl] = useState("");
  const [editDistribution, setEditDistribution] = useState("");
  const [editComponents, setEditComponents] = useState("");
  const [editArchitectures, setEditArchitectures] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  function openEdit(repo: RepositoryRead) {
    setEditing(repo);
    setEditArchiveUrl(repo.archive_url);
    setEditDistribution(repo.distribution);
    setEditComponents(repo.components.join(","));
    setEditArchitectures(repo.architectures.join(","));
    setEditError(null);
  }

  const updateMutation = useMutation({
    mutationFn: (payload: { name: string; archive_url: string; distribution: string; components: string[]; architectures: string[] }) =>
      updateRepository(payload.name, payload),
    onSuccess: () => {
      toast.success("Repository updated — sync again to pull from the new source");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      setEditing(null);
    },
    onError: (err) => setEditError(errorMessage(err)),
  });

  function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditError(null);
    updateMutation.mutate({
      name: editing.name,
      archive_url: editArchiveUrl,
      distribution: editDistribution,
      components: editComponents.split(",").map((s) => s.trim()).filter(Boolean),
      architectures: editArchitectures.split(",").map((s) => s.trim()).filter(Boolean),
    });
  }

  const deleteMutation = useMutation({
    mutationFn: (name: string) => deleteRepository(name),
    onSuccess: () => {
      toast.success("Repository deleted");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleDelete(repo: RepositoryRead) {
    if (!confirm(`Delete repository "${repo.name}"? This removes the aptly mirror and cannot be undone.`)) return;
    deleteMutation.mutate(repo.name);
  }

  function handleProbe(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    probeMutation.mutate(archiveUrl);
  }

  function toggleDistribution(name: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(name);
      else next.delete(name);
      return next;
    });
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (selected.size === 0) {
      setFormError("Select at least one distribution.");
      return;
    }
    createMutation.mutate({
      archive_url: archiveUrl,
      distributions: Array.from(selected),
      components: componentsInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      architectures: architecturesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
  }

  return (
    <div>
      <PageHeader
        title="Repositories"
        description="Upstream apt archives mirrored by aptly"
        actions={
          <RoleGate minRole="operator">
            <Dialog
              open={dialogOpen}
              onOpenChange={(open) => {
                setDialogOpen(open);
                if (!open) resetDialog();
              }}
            >
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New repository
                </Button>
              </DialogTrigger>
              <DialogContent>
                {distributions === null ? (
                  <form onSubmit={handleProbe}>
                    <DialogHeader>
                      <DialogTitle>Browse an archive</DialogTitle>
                      <DialogDescription>
                        Enter an upstream apt archive URL — groundctl lists the distributions it publishes so you
                        can pick which ones to mirror.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="mt-4 flex flex-col gap-4">
                      {formError && <p className="text-sm text-destructive">{formError}</p>}
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="archive-url">Archive URL</Label>
                        <Input
                          id="archive-url"
                          type="url"
                          value={archiveUrl}
                          onChange={(e) => setArchiveUrl(e.target.value)}
                          placeholder={DEFAULT_ARCHIVE_URL}
                          required
                        />
                      </div>
                    </div>
                    <DialogFooter className="mt-6">
                      <Button type="submit" disabled={probeMutation.isPending}>
                        <Search className="h-4 w-4" />
                        {probeMutation.isPending ? "Browsing…" : "Browse"}
                      </Button>
                    </DialogFooter>
                  </form>
                ) : (
                  <form onSubmit={handleCreate}>
                    <DialogHeader>
                      <DialogTitle>Select distributions</DialogTitle>
                      <DialogDescription>
                        Found {distributions.length} distributions at <code className="text-xs">{archiveUrl}</code>.
                        Pick the ones to mirror.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="mt-4 flex flex-col gap-4">
                      {formError && <p className="text-sm text-destructive">{formError}</p>}
                      <div className="flex max-h-64 flex-col gap-2 overflow-y-auto rounded-md border p-3">
                        {distributions.map((name) => (
                          <div key={name} className="flex items-center gap-2">
                            <Checkbox
                              id={`dist-${name}`}
                              checked={selected.has(name)}
                              onCheckedChange={(checked) => toggleDistribution(name, checked === true)}
                            />
                            <Label htmlFor={`dist-${name}`} className="flex-1 cursor-pointer font-normal">
                              {name}
                            </Label>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-xs text-muted-foreground"
                              disabled={estimateMutation.isPending && estimateMutation.variables?.distribution === name}
                              onClick={() => handleEstimate(name)}
                            >
                              {estimateMutation.isPending && estimateMutation.variables?.distribution === name
                                ? "Estimating…"
                                : estimateMutation.isSuccess && estimateMutation.variables?.distribution === name
                                  ? formatBytes(estimateMutation.data.size_bytes)
                                  : estimateMutation.isError && estimateMutation.variables?.distribution === name
                                    ? "Estimate failed"
                                    : "Estimate size"}
                            </Button>
                          </div>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Estimate reads upstream Packages metadata for the current components/architectures below —
                        it isn't exact and some distributions may not support it.
                      </p>
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="repo-components">Components (comma-separated)</Label>
                        <Input
                          id="repo-components"
                          value={componentsInput}
                          onChange={(e) => setComponentsInput(e.target.value)}
                          placeholder="main,universe"
                          required
                        />
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="repo-architectures">Architectures (comma-separated)</Label>
                        <Input
                          id="repo-architectures"
                          value={architecturesInput}
                          onChange={(e) => setArchitecturesInput(e.target.value)}
                          placeholder="amd64,arm64"
                          required
                        />
                      </div>
                    </div>
                    <DialogFooter className="mt-6 flex items-center justify-between sm:justify-between">
                      <Button type="button" variant="outline" onClick={() => setDistributions(null)}>
                        Back
                      </Button>
                      <Button type="submit" disabled={createMutation.isPending}>
                        {createMutation.isPending
                          ? "Creating…"
                          : `Create ${selected.size || ""} repositor${selected.size === 1 ? "y" : "ies"}`}
                      </Button>
                    </DialogFooter>
                  </form>
                )}
              </DialogContent>
            </Dialog>
          </RoleGate>
        }
      />

      <QueryState
        isLoading={repositoriesQuery.isLoading}
        isError={repositoriesQuery.isError}
        error={repositoriesQuery.error}
        isEmpty={repositoriesQuery.data?.length === 0}
        emptyMessage="No repositories yet. Create one to start mirroring an upstream archive."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Archive URL</TableHead>
              <TableHead>Distribution</TableHead>
              <TableHead>Components</TableHead>
              <TableHead>Architectures</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Last synced</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {repositoriesQuery.data?.map((repo) => (
              <TableRow key={repo.id}>
                <TableCell className="font-medium">
                  <Link to={`/repositories/${encodeURIComponent(repo.name)}`} className="hover:underline">
                    {repo.name}
                  </Link>
                </TableCell>
                <TableCell className="max-w-64 truncate text-muted-foreground" title={repo.archive_url}>
                  {repo.archive_url}
                </TableCell>
                <TableCell>{repo.distribution}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {repo.components.map((c) => (
                      <Badge key={c} variant="outline">
                        {c}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{repo.architectures.join(", ")}</TableCell>
                <TableCell className="text-muted-foreground">{formatBytes(repo.size_bytes)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {repo.last_sync_job_id ? (
                    <Link to={`/jobs/${repo.last_sync_job_id}`} className="hover:underline">
                      {formatDateTime(repo.last_synced_at)}
                      {repo.last_synced_at === null && " (view job)"}
                    </Link>
                  ) : (
                    formatDateTime(repo.last_synced_at)
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <RoleGate minRole="operator">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm">
                          <MoreHorizontal className="h-3.5 w-3.5" />
                          <span className="sr-only">Actions for {repo.name}</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          className="gap-2"
                          disabled={syncMutation.isPending && syncMutation.variables === repo.name}
                          onClick={() => syncMutation.mutate(repo.name)}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Sync
                        </DropdownMenuItem>
                        <DropdownMenuItem className="gap-2" onClick={() => openEdit(repo)}>
                          <Pencil className="h-3.5 w-3.5" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="gap-2 text-destructive focus:text-destructive"
                          disabled={deleteMutation.isPending && deleteMutation.variables === repo.name}
                          onClick={() => handleDelete(repo)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </RoleGate>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <form onSubmit={handleUpdate}>
            <DialogHeader>
              <DialogTitle>Edit {editing?.name}</DialogTitle>
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
              <Button type="button" variant="outline" onClick={() => setEditing(null)}>
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
