import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Plus, Rocket, Trash2, UploadCloud } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RoleGate } from "@/layout/RoleGate";
import {
  getContentView,
  listContentViewVersions,
  listContentViewFilters,
  listContentViewEnvironments,
  createContentViewFilter,
  deleteContentViewFilter,
  deleteContentView,
  deleteContentViewVersion,
  publishContentView,
  publishAndPromoteContentView,
  updateContentViewVersion,
  type ContentViewVersionRead,
  type FilterType,
} from "@/api/contentViews";
import { listRepositories } from "@/api/repositories";
import { listLifecycleEnvironments, promoteEnvironmentContentView } from "@/api/environments";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

const FILTER_TYPE_LABEL: Record<FilterType, string> = {
  include: "Include",
  exclude: "Exclude",
  errata_since: "Errata since",
};

export function ContentViewDetailPage() {
  const { contentViewId } = useParams<{ contentViewId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filterType, setFilterType] = useState<FilterType>("include");
  const [pattern, setPattern] = useState("");
  const [filterError, setFilterError] = useState<string | null>(null);

  if (!contentViewId) return null;

  const viewQuery = useQuery({
    queryKey: ["content-view", contentViewId],
    queryFn: () => getContentView(contentViewId),
  });

  const repositoriesQuery = useQuery({ queryKey: ["repositories"], queryFn: () => listRepositories({ limit: 100 }) });
  const repoNameById = new Map((repositoriesQuery.data ?? []).map((r) => [r.id, r.name]));

  const versionsQuery = useQuery({
    queryKey: ["content-view-versions", contentViewId],
    queryFn: () => listContentViewVersions(contentViewId, { limit: 50 }),
  });

  const filtersQuery = useQuery({
    queryKey: ["content-view-filters", contentViewId],
    queryFn: () => listContentViewFilters(contentViewId),
  });

  // Valid promote targets: environments this content view is ALREADY
  // assigned to (EnvironmentContentView, models.py) — assigning it to a
  // NEW environment for the first time happens from the Environments
  // page instead (Assign content view), since that's where an operator
  // picks which environment, not from here.
  const assignmentsQuery = useQuery({
    queryKey: ["content-view-environments", contentViewId],
    queryFn: () => listContentViewEnvironments(contentViewId),
  });
  const allEnvironmentsQuery = useQuery({
    queryKey: ["environments"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });
  const environmentNameById = new Map((allEnvironmentsQuery.data ?? []).map((env) => [env.id, env.name]));

  const filterMutation = useMutation({
    mutationFn: () => createContentViewFilter(contentViewId, { filter_type: filterType, pattern }),
    onSuccess: () => {
      toast.success("Filter added");
      setPattern("");
      setFilterError(null);
      void queryClient.invalidateQueries({ queryKey: ["content-view-filters", contentViewId] });
    },
    onError: (err) => setFilterError(errorMessage(err)),
  });

  const deleteFilterMutation = useMutation({
    mutationFn: (filterId: string) => deleteContentViewFilter(contentViewId, filterId),
    onSuccess: () => {
      toast.success("Filter removed");
      void queryClient.invalidateQueries({ queryKey: ["content-view-filters", contentViewId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createDescription, setCreateDescription] = useState("");
  const [createPromoteNow, setCreatePromoteNow] = useState(false);
  const [createEnvironmentId, setCreateEnvironmentId] = useState("");
  const [createAllowUnsigned, setCreateAllowUnsigned] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const selectedCreateAssignment = assignmentsQuery.data?.find((ecv) => ecv.environment_id === createEnvironmentId);
  const createNeedsSigningChoice = !selectedCreateAssignment?.gpg_key_id;

  // Always cuts a new version, even with nothing changed since the latest
  // (a version doubles as a promotion checkpoint, not purely a
  // content-change record) — matches the old one-click button's behavior.
  //
  // Two different backends depending on whether "promote now" is checked:
  // promoting means a real aptly publish/switch-publish call that can run
  // long, so that path goes through publishAndPromoteContentView (a
  // tracked Job — navigates to its status page). Just creating a version
  // with no promote is exactly as fast as it always was, so it stays on
  // the plain synchronous publishContentView, with the description
  // applied via a follow-up PATCH (no combined "publish with description,
  // don't promote" endpoint exists — see PATCH .../versions/{id}'s own
  // docstring for why description-setting is deliberately separate from
  // publish).
  const createVersionMutation = useMutation({
    mutationFn: async () => {
      if (createPromoteNow) {
        const job = await publishAndPromoteContentView(contentViewId, {
          environment_id: createEnvironmentId,
          force: true,
          description: createDescription || null,
          allow_unsigned: createAllowUnsigned,
        });
        return { kind: "job" as const, job };
      }
      const result = await publishContentView(contentViewId, true);
      if (createDescription) {
        await updateContentViewVersion(contentViewId, result.content_view_version.id, createDescription);
      }
      return { kind: "version" as const, version: result.content_view_version };
    },
    onSuccess: (result) => {
      setCreateDialogOpen(false);
      setCreateDescription("");
      setCreatePromoteNow(false);
      setCreateEnvironmentId("");
      setCreateAllowUnsigned(false);
      setCreateError(null);
      if (result.kind === "job") {
        toast.success("Version creation + promotion started");
        void queryClient.invalidateQueries({ queryKey: ["content-view-versions", contentViewId] });
        navigate(`/jobs/${result.job.id}`);
      } else {
        toast.success(`Created version ${result.version.version}`);
        void queryClient.invalidateQueries({ queryKey: ["content-view-versions", contentViewId] });
      }
    },
    onError: (err) => setCreateError(errorMessage(err)),
  });

  function openCreateVersion() {
    setCreateDescription("");
    setCreatePromoteNow(false);
    setCreateEnvironmentId("");
    setCreateAllowUnsigned(false);
    setCreateError(null);
    setCreateDialogOpen(true);
  }

  function handleCreateVersion(e: FormEvent) {
    e.preventDefault();
    if (createPromoteNow && !createEnvironmentId) {
      setCreateError("select an environment to promote to");
      return;
    }
    if (createPromoteNow && createNeedsSigningChoice && !createAllowUnsigned) {
      setCreateError('this environment has no signing key configured — enable "Allow unsigned" to proceed');
      return;
    }
    setCreateError(null);
    createVersionMutation.mutate();
  }

  const deleteViewMutation = useMutation({
    mutationFn: () => deleteContentView(contentViewId),
    onSuccess: () => {
      toast.success("Content view deleted");
      void queryClient.invalidateQueries({ queryKey: ["content-views"] });
      navigate("/content-views");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const [promotingVersion, setPromotingVersion] = useState<ContentViewVersionRead | null>(null);
  const [promoteEnvironmentId, setPromoteEnvironmentId] = useState<string>("");
  const [promoteError, setPromoteError] = useState<string | null>(null);

  // Only environments this content view is ALREADY assigned to are valid
  // targets here — every one of them already had its first promote (see
  // assign-and-first-promote on the Environments page), so there's no
  // signing choice left to make; gpg_key_id is already locked in.
  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteEnvironmentContentView(promoteEnvironmentId, contentViewId, {
        content_view_version_id: promotingVersion!.id,
      }),
    onSuccess: (result) => {
      toast.success(`Promoted version ${promotingVersion!.version} — live at ${result.published_url}`);
      setPromotingVersion(null);
      setPromoteEnvironmentId("");
      setPromoteError(null);
      void queryClient.invalidateQueries({ queryKey: ["content-view-environments", contentViewId] });
    },
    onError: (err) => setPromoteError(errorMessage(err)),
  });

  function openPromote(version: ContentViewVersionRead) {
    setPromotingVersion(version);
    setPromoteEnvironmentId("");
    setPromoteError(null);
  }

  function handlePromote(e: FormEvent) {
    e.preventDefault();
    if (!promoteEnvironmentId) {
      setPromoteError("select an environment");
      return;
    }
    setPromoteError(null);
    promoteMutation.mutate();
  }

  const [editingVersion, setEditingVersion] = useState<ContentViewVersionRead | null>(null);
  const [editVersionDescription, setEditVersionDescription] = useState("");

  const updateVersionMutation = useMutation({
    mutationFn: () =>
      updateContentViewVersion(contentViewId, editingVersion!.id, editVersionDescription || null),
    onSuccess: () => {
      toast.success(`Updated version ${editingVersion!.version}`);
      setEditingVersion(null);
      void queryClient.invalidateQueries({ queryKey: ["content-view-versions", contentViewId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function openEditVersion(version: ContentViewVersionRead) {
    setEditingVersion(version);
    setEditVersionDescription(version.description ?? "");
  }

  const deleteVersionMutation = useMutation({
    mutationFn: (version: ContentViewVersionRead) => deleteContentViewVersion(contentViewId, version.id),
    onSuccess: (job) => {
      toast.success("Version deletion started");
      navigate(`/jobs/${job.id}`);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleDeleteVersion(version: ContentViewVersionRead) {
    if (!confirm(`Delete version ${version.version}? This removes its aptly snapshots and cannot be undone.`)) return;
    deleteVersionMutation.mutate(version);
  }

  function handleAddFilter(e: FormEvent) {
    e.preventDefault();
    setFilterError(null);
    filterMutation.mutate();
  }

  function handleDeleteView() {
    if (!view) return;
    if (!confirm(`Delete content view "${view.name}"? This removes its version history and filters and cannot be undone.`)) return;
    deleteViewMutation.mutate();
  }

  const view = viewQuery.data;

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/content-views")}>
        <ArrowLeft className="h-4 w-4" />
        Back to content views
      </Button>

      <QueryState isLoading={viewQuery.isLoading} isError={viewQuery.isError} error={viewQuery.error}>
        {view && (
          <div className="flex flex-col gap-6">
            <PageHeader
              title={view.name}
              description={
                view.description
                  ? `${view.description} · ${view.repository_ids.length} repositor${view.repository_ids.length === 1 ? "y" : "ies"}`
                  : `${view.repository_ids.length} repositor${view.repository_ids.length === 1 ? "y" : "ies"}`
              }
              actions={
                <RoleGate minRole="operator">
                  <div className="flex gap-2">
                    <Button size="sm" onClick={openCreateVersion}>
                      <UploadCloud className="h-4 w-4" />
                      Create new version
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={deleteViewMutation.isPending}
                      onClick={handleDeleteView}
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </Button>
                  </div>
                </RoleGate>
              }
            />

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Repositories</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {view.repository_ids.length === 0 ? (
                  <p className="text-sm text-muted-foreground">None.</p>
                ) : (
                  view.repository_ids.map((id) => (
                    <Badge key={id} variant="outline">
                      {repoNameById.get(id) ?? id}
                    </Badge>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Filters</CardTitle>
                <CardDescription>Include/exclude packages by pattern, or scope to errata since a date.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <QueryState
                  isLoading={filtersQuery.isLoading}
                  isError={filtersQuery.isError}
                  error={filtersQuery.error}
                  isEmpty={filtersQuery.data?.length === 0}
                  emptyMessage="No filters — this content view includes every package from its repositories."
                >
                  <ul className="flex flex-col divide-y rounded-lg border">
                    {filtersQuery.data?.map((f) => (
                      <li key={f.id} className="flex items-center justify-between px-3 py-2 text-sm">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{FILTER_TYPE_LABEL[f.filter_type]}</Badge>
                          <span className="font-mono text-xs">{f.pattern}</span>
                        </div>
                        <RoleGate minRole="operator">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-muted-foreground hover:text-destructive"
                            disabled={deleteFilterMutation.isPending && deleteFilterMutation.variables === f.id}
                            onClick={() => deleteFilterMutation.mutate(f.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </RoleGate>
                      </li>
                    ))}
                  </ul>
                </QueryState>

                <RoleGate minRole="operator">
                  <form onSubmit={handleAddFilter} className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-end">
                    {filterError && <p className="text-sm text-destructive sm:basis-full">{filterError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label>Type</Label>
                      <Select value={filterType} onValueChange={(v) => setFilterType(v as FilterType)}>
                        <SelectTrigger className="w-40">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="include">Include</SelectItem>
                          <SelectItem value="exclude">Exclude</SelectItem>
                          <SelectItem value="errata_since">Errata since</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex flex-1 flex-col gap-1.5">
                      <Label htmlFor="filter-pattern">{filterType === "errata_since" ? "Date" : "Pattern"}</Label>
                      <Input
                        id="filter-pattern"
                        type={filterType === "errata_since" ? "date" : "text"}
                        value={pattern}
                        onChange={(e) => setPattern(e.target.value)}
                        placeholder={filterType === "errata_since" ? undefined : "package-name or glob"}
                        required
                      />
                    </div>
                    <Button type="submit" disabled={filterMutation.isPending}>
                      <Plus className="h-4 w-4" />
                      Add filter
                    </Button>
                  </form>
                </RoleGate>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Version history</CardTitle>
              </CardHeader>
              <CardContent>
                <QueryState
                  isLoading={versionsQuery.isLoading}
                  isError={versionsQuery.isError}
                  error={versionsQuery.error}
                  isEmpty={versionsQuery.data?.length === 0}
                  emptyMessage="No versions published yet."
                >
                  <ul className="flex flex-col divide-y">
                    {versionsQuery.data?.map((v, i) => {
                      const liveOn = (assignmentsQuery.data ?? []).filter((ecv) => ecv.current_version_id === v.id);
                      // Versions are server-ordered newest-first, so the
                      // next array entry is the immediately preceding
                      // version — lets each row show "+N/-N packages vs
                      // vPrev" the way Satellite's version list does.
                      const previous = versionsQuery.data?.[i + 1];
                      const delta =
                        v.package_count !== null && previous?.package_count != null
                          ? v.package_count - previous.package_count
                          : null;
                      return (
                        <li key={v.id} className="py-3">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-medium">Version {v.version}</span>
                              {v.package_count !== null && (
                                <span className="text-xs text-muted-foreground">
                                  {v.package_count.toLocaleString()} package{v.package_count === 1 ? "" : "s"}
                                  {delta !== null && delta !== 0 && (
                                    <span className={delta > 0 ? "text-success" : "text-destructive"}>
                                      {" "}
                                      ({delta > 0 ? "+" : ""}
                                      {delta})
                                    </span>
                                  )}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-xs text-muted-foreground">{formatDateTime(v.published_at)}</span>
                              <RoleGate minRole="operator">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1.5 px-2 text-xs"
                                  onClick={() => openEditVersion(v)}
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                  Edit
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1.5 px-2 text-xs"
                                  onClick={() => openPromote(v)}
                                >
                                  <Rocket className="h-3.5 w-3.5" />
                                  Promote to…
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1.5 px-2 text-xs text-destructive hover:text-destructive"
                                  disabled={
                                    liveOn.length > 0 ||
                                    (deleteVersionMutation.isPending && deleteVersionMutation.variables?.id === v.id)
                                  }
                                  title={liveOn.length > 0 ? "Live on an environment — cannot be deleted" : undefined}
                                  onClick={() => handleDeleteVersion(v)}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                  Delete
                                </Button>
                              </RoleGate>
                            </div>
                          </div>
                          {v.description && <p className="mt-1 text-xs text-muted-foreground">{v.description}</p>}
                          <div className="mt-2 flex flex-wrap gap-1">
                            {v.snapshots.map((s) => (
                              <Badge key={`${s.repository_id}-${s.component}`} variant="outline">
                                {s.repository_name}/{s.component}
                              </Badge>
                            ))}
                          </div>
                          {liveOn.length > 0 && (
                            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                              <span className="text-muted-foreground">Live on:</span>
                              {liveOn.map((ecv) => (
                                <Badge key={ecv.id} variant="success">
                                  {environmentNameById.get(ecv.environment_id) ?? ecv.environment_id.slice(0, 8)}
                                </Badge>
                              ))}
                            </div>
                          )}
                          <p className="mt-1 truncate text-xs text-muted-foreground" title={v.content_hash}>
                            hash: {v.content_hash}
                          </p>
                        </li>
                      );
                    })}
                  </ul>
                </QueryState>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>

      <Dialog open={promotingVersion !== null} onOpenChange={(open) => !open && setPromotingVersion(null)}>
        <DialogContent>
          <form onSubmit={handlePromote}>
            <DialogHeader>
              <DialogTitle>Promote version {promotingVersion?.version}</DialogTitle>
              <DialogDescription>
                Points the chosen environment's publish prefix at this version — clients synced to that environment
                will pick it up on their next `apt update`. A path environment beyond position 0 requires its
                predecessor to already be live on this version first.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-4">
              {promoteError && <p className="text-sm text-destructive">{promoteError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label>Environment</Label>
                {assignmentsQuery.data?.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    This content view isn't assigned to any environment yet — assign it from the Environments page
                    first.
                  </p>
                ) : (
                  <Select value={promoteEnvironmentId} onValueChange={setPromoteEnvironmentId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select an environment" />
                    </SelectTrigger>
                    <SelectContent>
                      {assignmentsQuery.data?.map((ecv) => (
                        <SelectItem key={ecv.environment_id} value={ecv.environment_id}>
                          {environmentNameById.get(ecv.environment_id) ?? ecv.environment_id.slice(0, 8)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setPromotingVersion(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={promoteMutation.isPending || assignmentsQuery.data?.length === 0}>
                {promoteMutation.isPending ? "Promoting…" : "Promote"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={editingVersion !== null} onOpenChange={(open) => !open && setEditingVersion(null)}>
        <DialogContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              updateVersionMutation.mutate();
            }}
          >
            <DialogHeader>
              <DialogTitle>Edit version {editingVersion?.version}</DialogTitle>
              <DialogDescription>
                Annotation only — the version number stays the permanent identifier.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-1.5">
              <Label htmlFor="version-description">Description</Label>
              <Textarea
                id="version-description"
                value={editVersionDescription}
                onChange={(e) => setEditVersionDescription(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setEditingVersion(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={updateVersionMutation.isPending}>
                {updateVersionMutation.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <form onSubmit={handleCreateVersion}>
            <DialogHeader>
              <DialogTitle>Create new version</DialogTitle>
              <DialogDescription>
                Cuts a new version from the member repositories' current content. Optionally promote it to an
                environment right away — that runs as a tracked job you can follow from the Jobs page.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-4">
              {createError && <p className="text-sm text-destructive">{createError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="create-version-description">Description</Label>
                <Textarea
                  id="create-version-description"
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="create-promote-now"
                  checked={createPromoteNow}
                  onCheckedChange={(checked) => setCreatePromoteNow(checked === true)}
                />
                <Label htmlFor="create-promote-now" className="cursor-pointer font-normal">
                  Promote to an environment now
                </Label>
              </div>
              {createPromoteNow && (
                <div className="flex flex-col gap-1.5">
                  <Label>Environment</Label>
                  {assignmentsQuery.data?.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      This content view isn't assigned to any environment yet — assign it from the Environments
                      page first.
                    </p>
                  ) : (
                    <Select value={createEnvironmentId} onValueChange={setCreateEnvironmentId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select an environment" />
                      </SelectTrigger>
                      <SelectContent>
                        {assignmentsQuery.data?.map((ecv) => (
                          <SelectItem key={ecv.environment_id} value={ecv.environment_id}>
                            {environmentNameById.get(ecv.environment_id) ?? ecv.environment_id.slice(0, 8)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              )}
              {createPromoteNow && createNeedsSigningChoice && (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="create-allow-unsigned"
                    checked={createAllowUnsigned}
                    onCheckedChange={(checked) => setCreateAllowUnsigned(checked === true)}
                  />
                  <Label htmlFor="create-allow-unsigned" className="cursor-pointer font-normal">
                    Allow unsigned (not recommended) — this environment has no GPG key configured
                  </Label>
                </div>
              )}
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setCreateDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  createVersionMutation.isPending || (createPromoteNow && assignmentsQuery.data?.length === 0)
                }
              >
                {createVersionMutation.isPending
                  ? "Creating…"
                  : createPromoteNow
                    ? "Create & promote"
                    : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
