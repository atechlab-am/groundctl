import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { FolderCog, MoreHorizontal, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { JobStatusIndicator } from "@/components/JobStatusIndicator";
import { RepositoryHealthBadge } from "@/components/RepositoryHealthBadge";
import { RoleGate } from "@/layout/RoleGate";
import { useHasRole } from "@/auth/useHasRole";
import {
  listRepositories,
  probeRepositoryArchive,
  createRepositoriesBatch,
  syncRepository,
  estimateRepositorySize,
  updateRepository,
  updateRepositoryAutoSync,
  updateRepositoryProduct,
  deleteRepository,
  type RepositoryRead,
} from "@/api/repositories";
import { listProducts, createProduct, updateProduct, deleteProduct, type ProductRead } from "@/api/products";
import { getJob } from "@/api/jobs";
import { formatDateTime, formatBytes } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

const UNGROUPED = "__ungrouped__";

const DEFAULT_ARCHIVE_URL = "http://archive.ubuntu.com/ubuntu";

// Shows live job status (spinner/elapsed/log) while a Sync/Edit/Delete
// triggered from this page is running (activeJobId, in-memory). After a
// page reload that state is gone, so this also polls repo.last_job_id
// (persisted — set by Sync/Edit/Delete alike, unlike last_sync_job_id
// which only ever tracks Sync) just enough to know if IT is still
// in-progress; only then does it render the full indicator. Otherwise
// falls back to the plain last-synced date, same as before last_job_id
// existed — avoids every row permanently sprouting a status badge/log
// toggle for jobs that finished long ago.
function RepositoryStatusCell({ repo, activeJobId }: { repo: RepositoryRead; activeJobId: string | undefined }) {
  const lastJobId = activeJobId ?? repo.last_job_id ?? undefined;

  const lastJobQuery = useQuery({
    queryKey: ["job", lastJobId],
    queryFn: () => getJob(lastJobId!),
    enabled: lastJobId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  const job = lastJobQuery.data;
  const inProgress = job?.status === "pending" || job?.status === "running";

  if (activeJobId || inProgress) {
    return <JobStatusIndicator jobId={lastJobId as string} />;
  }
  if (repo.last_sync_job_id) {
    return (
      <Link to={`/jobs/${repo.last_sync_job_id}`} className="hover:underline">
        {formatDateTime(repo.last_synced_at)}
        {repo.last_synced_at === null && " (view job)"}
      </Link>
    );
  }
  return <>{formatDateTime(repo.last_synced_at)}</>;
}

export function RepositoriesPage() {
  const queryClient = useQueryClient();
  const canOperate = useHasRole("operator");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [archiveUrl, setArchiveUrl] = useState(DEFAULT_ARCHIVE_URL);
  const [distributions, setDistributions] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [componentsInput, setComponentsInput] = useState("main,universe");
  const [architecturesInput, setArchitecturesInput] = useState("amd64");
  const [formError, setFormError] = useState<string | null>(null);
  // Tracks the most recently triggered Sync/Edit/Delete job per repo name,
  // so its row can show live status without navigating away — separate
  // from RepositoryRead.last_sync_job_id, since a Delete's Job outlives
  // the Repository row it targeted (that row is gone by the time the job
  // finishes) and Edit's Job isn't tracked on the row at all.
  const [activeJobByRepo, setActiveJobByRepo] = useState<Record<string, string>>({});

  // Polled, not just invalidated on your own mutations — a background job
  // (yours from an earlier visit, or anyone else's) keeps running via
  // Celery regardless of whether this page is open; without a poll here,
  // fields like size_bytes/last_synced_at on the Repository row itself
  // only updated when something local invalidated the query, so a sync
  // that finished while you were just looking at the page (not the one
  // who triggered it) appeared stuck until a manual reload.
  const repositoriesQuery = useQuery({
    queryKey: ["repositories"],
    queryFn: () => listRepositories({ limit: 100 }),
    refetchInterval: 10_000,
  });

  const productsQuery = useQuery({
    queryKey: ["products"],
    queryFn: listProducts,
  });

  const groupedRepositories = useMemo(() => {
    const repos = repositoriesQuery.data ?? [];
    const groups = new Map<string, RepositoryRead[]>();
    for (const repo of repos) {
      const key = repo.product_id ?? UNGROUPED;
      const list = groups.get(key);
      if (list) list.push(repo);
      else groups.set(key, [repo]);
    }
    const productGroups = (productsQuery.data ?? [])
      .filter((p) => groups.has(p.id))
      .map((p) => ({ key: p.id, label: p.name, repos: groups.get(p.id)! }));
    const ungrouped = groups.get(UNGROUPED);
    return ungrouped ? [...productGroups, { key: UNGROUPED, label: "Ungrouped", repos: ungrouped }] : productGroups;
  }, [repositoriesQuery.data, productsQuery.data]);

  const [manageProductsOpen, setManageProductsOpen] = useState(false);
  const [newProductName, setNewProductName] = useState("");
  const [newProductDescription, setNewProductDescription] = useState("");
  const [productError, setProductError] = useState<string | null>(null);
  const [editingProduct, setEditingProduct] = useState<ProductRead | null>(null);
  const [editProductName, setEditProductName] = useState("");
  const [editProductDescription, setEditProductDescription] = useState("");
  const [assigningProduct, setAssigningProduct] = useState<RepositoryRead | null>(null);

  const createProductMutation = useMutation({
    mutationFn: createProduct,
    onSuccess: () => {
      toast.success("Product created");
      setNewProductName("");
      setNewProductDescription("");
      setProductError(null);
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (err) => setProductError(errorMessage(err)),
  });

  const updateProductMutation = useMutation({
    mutationFn: (payload: { id: string; name: string; description: string | null }) =>
      updateProduct(payload.id, { name: payload.name, description: payload.description }),
    onSuccess: () => {
      toast.success("Product updated");
      setEditingProduct(null);
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (err) => setProductError(errorMessage(err)),
  });

  const deleteProductMutation = useMutation({
    mutationFn: deleteProduct,
    onSuccess: () => {
      toast.success("Product deleted — its repositories are now ungrouped");
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const setRepoProductMutation = useMutation({
    mutationFn: (payload: { name: string; productId: string | null }) =>
      updateRepositoryProduct(payload.name, payload.productId),
    onSuccess: () => {
      toast.success("Product assignment updated");
      setAssigningProduct(null);
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleCreateProduct(e: React.FormEvent) {
    e.preventDefault();
    if (!newProductName.trim()) {
      setProductError("Name is required.");
      return;
    }
    setProductError(null);
    createProductMutation.mutate({
      name: newProductName.trim(),
      description: newProductDescription.trim() || null,
    });
  }

  function openEditProduct(product: ProductRead) {
    setEditingProduct(product);
    setEditProductName(product.name);
    setEditProductDescription(product.description ?? "");
    setProductError(null);
  }

  function handleUpdateProduct(e: React.FormEvent) {
    e.preventDefault();
    if (!editingProduct) return;
    setProductError(null);
    updateProductMutation.mutate({
      id: editingProduct.id,
      name: editProductName.trim(),
      description: editProductDescription.trim() || null,
    });
  }

  function handleDeleteProduct(product: ProductRead) {
    if (
      !confirm(
        `Delete product "${product.name}"? Its ${product.repository_count} repositor${product.repository_count === 1 ? "y" : "ies"} will become ungrouped.`,
      )
    )
      return;
    deleteProductMutation.mutate(product.id);
  }

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
    onSuccess: (job, name) => {
      toast.success("Sync triggered");
      setActiveJobByRepo((m) => ({ ...m, [name]: job.id }));
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
    onSuccess: (job, payload) => {
      toast.success("Update triggered");
      setActiveJobByRepo((m) => ({ ...m, [payload.name]: job.id }));
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
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
    onSuccess: (job, name) => {
      toast.success("Delete triggered — the repository disappears from this list once it finishes");
      setActiveJobByRepo((m) => ({ ...m, [name]: job.id }));
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleDelete(repo: RepositoryRead) {
    if (!confirm(`Delete repository "${repo.name}"? This removes the aptly mirror and cannot be undone.`)) return;
    deleteMutation.mutate(repo.name);
  }

  const autoSyncMutation = useMutation({
    mutationFn: (payload: { name: string; enabled: boolean }) =>
      updateRepositoryAutoSync(payload.name, payload.enabled),
    onSuccess: (_repo, payload) => {
      toast.success(payload.enabled ? "Nightly auto-sync enabled" : "Nightly auto-sync disabled");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

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
            <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setManageProductsOpen(true)}>
              <FolderCog className="h-4 w-4" />
              Manage products
            </Button>
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
            </div>
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
              <TableHead>Packages</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Health</TableHead>
              <TableHead>Last synced</TableHead>
              <TableHead>Nightly sync</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groupedRepositories.map((group) => (
              <Fragment key={group.key}>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableCell colSpan={11} className="py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}
                    <span className="ml-2 font-normal normal-case text-muted-foreground/70">
                      ({group.repos.length})
                    </span>
                  </TableCell>
                </TableRow>
                {group.repos.map((repo) => (
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
                    <TableCell className="text-muted-foreground">
                      {repo.package_count === null ? "—" : repo.package_count.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatBytes(repo.size_bytes)}</TableCell>
                    <TableCell>
                      <RepositoryHealthBadge status={repo.health_status} />
                    </TableCell>
                    <TableCell className="min-w-40 text-muted-foreground">
                      <RepositoryStatusCell repo={repo} activeJobId={activeJobByRepo[repo.name]} />
                    </TableCell>
                    <TableCell>
                      {canOperate ? (
                        <Checkbox
                          checked={repo.auto_sync_enabled}
                          disabled={autoSyncMutation.isPending && autoSyncMutation.variables?.name === repo.name}
                          onCheckedChange={(checked) =>
                            autoSyncMutation.mutate({ name: repo.name, enabled: checked === true })
                          }
                          aria-label={`Nightly auto-sync for ${repo.name}`}
                        />
                      ) : (
                        <span className="text-sm text-muted-foreground">{repo.auto_sync_enabled ? "On" : "Off"}</span>
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
                          <DropdownMenuContent align="end" className="w-56">
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
                            <DropdownMenuItem className="gap-2" onClick={() => setAssigningProduct(repo)}>
                              <FolderCog className="h-3.5 w-3.5" />
                              Set product…
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
              </Fragment>
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

      <Dialog open={assigningProduct !== null} onOpenChange={(open) => !open && setAssigningProduct(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set product for {assigningProduct?.name}</DialogTitle>
            <DialogDescription>
              Purely organizational — has no effect on sync/publish/content-view behavior.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <Select
              value={assigningProduct?.product_id ?? UNGROUPED}
              onValueChange={(value) => {
                if (!assigningProduct) return;
                setRepoProductMutation.mutate({
                  name: assigningProduct.name,
                  productId: value === UNGROUPED ? null : value,
                });
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNGROUPED}>Ungrouped</SelectItem>
                {(productsQuery.data ?? []).map((product) => (
                  <SelectItem key={product.id} value={product.id}>
                    {product.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter className="mt-6">
            <Button variant="outline" onClick={() => setAssigningProduct(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={manageProductsOpen} onOpenChange={setManageProductsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manage products</DialogTitle>
            <DialogDescription>
              Products group related repositories (e.g. jammy + jammy-security + jammy-updates as
              "ubuntu-22.04"). Same name rules as a repository — letters, numbers, dots, underscores,
              hyphens, no spaces. Purely organizational — deleting a product just ungroups its repositories.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 flex flex-col gap-4">
            {productError && <p className="text-sm text-destructive">{productError}</p>}
            <div className="flex flex-col gap-2 max-h-56 overflow-y-auto rounded-md border p-2">
              {(productsQuery.data ?? []).length === 0 && (
                <p className="px-2 py-1 text-sm text-muted-foreground">No products yet.</p>
              )}
              {productsQuery.data?.map((product) => (
                <div key={product.id} className="flex items-center justify-between gap-2 rounded px-2 py-1.5 hover:bg-muted/50">
                  {editingProduct?.id === product.id ? (
                    <form onSubmit={handleUpdateProduct} className="flex flex-1 items-center gap-2">
                      <Input
                        value={editProductName}
                        onChange={(e) => setEditProductName(e.target.value)}
                        className="h-8"
                        autoFocus
                        required
                      />
                      <Input
                        value={editProductDescription}
                        onChange={(e) => setEditProductDescription(e.target.value)}
                        placeholder="Description (optional)"
                        className="h-8"
                      />
                      <Button type="submit" size="sm" disabled={updateProductMutation.isPending}>
                        Save
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => setEditingProduct(null)}>
                        Cancel
                      </Button>
                    </form>
                  ) : (
                    <>
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-sm font-medium">{product.name}</span>
                        {product.description && (
                          <span className="truncate text-xs text-muted-foreground">{product.description}</span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {product.repository_count} repo{product.repository_count === 1 ? "" : "s"}
                      </span>
                      <Button variant="ghost" size="sm" onClick={() => openEditProduct(product)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => handleDeleteProduct(product)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  )}
                </div>
              ))}
            </div>
            <form onSubmit={handleCreateProduct} className="flex items-end gap-2 border-t pt-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="new-product-name">New product name</Label>
                <Input
                  id="new-product-name"
                  value={newProductName}
                  onChange={(e) => setNewProductName(e.target.value)}
                  placeholder="ubuntu-22.04"
                  required
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="new-product-description">Description (optional)</Label>
                <Input
                  id="new-product-description"
                  value={newProductDescription}
                  onChange={(e) => setNewProductDescription(e.target.value)}
                />
              </div>
              <Button type="submit" disabled={createProductMutation.isPending}>
                <Plus className="h-4 w-4" />
                Add
              </Button>
            </form>
          </div>
          <DialogFooter className="mt-6">
            <Button variant="outline" onClick={() => setManageProductsOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
