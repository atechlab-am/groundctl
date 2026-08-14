import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Plus, Rocket, Trash2, UploadCloud } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
  createContentViewFilter,
  deleteContentViewFilter,
  deleteContentView,
  publishContentView,
  type ContentViewVersionRead,
  type FilterType,
} from "@/api/contentViews";
import { listRepositories } from "@/api/repositories";
import { listLifecycleEnvironments, promoteEnvironment } from "@/api/environments";
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

  // Only environments whose content_view_id is this one are valid promote
  // targets — promoteEnvironment resolves the version against the
  // environment's OWN content_view_id server-side, so offering an
  // environment on a different content view would just 404.
  const environmentsQuery = useQuery({
    queryKey: ["lifecycle-environments", "content-view", contentViewId],
    queryFn: () => listLifecycleEnvironments({ content_view_id: contentViewId, limit: 100 }),
  });

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

  // Always force=true — "Create new version" always cuts one, even with
  // nothing changed since the latest (a version doubles as a promotion
  // checkpoint, not purely a content-change record).
  const publishMutation = useMutation({
    mutationFn: () => publishContentView(contentViewId, true),
    onSuccess: (result) => {
      toast.success(`Created version ${result.content_view_version.version}`);
      void queryClient.invalidateQueries({ queryKey: ["content-view-versions", contentViewId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

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

  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteEnvironment(promoteEnvironmentId, {
        content_view_version_id: promotingVersion!.id,
      }),
    onSuccess: (result) => {
      toast.success(`Promoted version ${promotingVersion!.version} — live at ${result.published_url}`);
      setPromotingVersion(null);
      setPromoteEnvironmentId("");
      setPromoteError(null);
      void queryClient.invalidateQueries({ queryKey: ["lifecycle-environments", "content-view", contentViewId] });
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
              description={`${view.repository_ids.length} repositor${view.repository_ids.length === 1 ? "y" : "ies"}`}
              actions={
                <RoleGate minRole="operator">
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending}>
                      <UploadCloud className="h-4 w-4" />
                      {publishMutation.isPending ? "Creating…" : "Create new version"}
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
                      const liveOn = (environmentsQuery.data ?? []).filter((env) => env.current_version_id === v.id);
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
                                  onClick={() => openPromote(v)}
                                >
                                  <Rocket className="h-3.5 w-3.5" />
                                  Promote to…
                                </Button>
                              </RoleGate>
                            </div>
                          </div>
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
                              {liveOn.map((env) => (
                                <Badge key={env.id} variant="success">
                                  {env.name}
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
                {environmentsQuery.data?.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No lifecycle environments use this content view yet.
                  </p>
                ) : (
                  <Select value={promoteEnvironmentId} onValueChange={setPromoteEnvironmentId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select an environment" />
                    </SelectTrigger>
                    <SelectContent>
                      {environmentsQuery.data?.map((env) => (
                        <SelectItem key={env.id} value={env.id}>
                          {env.name} ({env.path_name}, position {env.position})
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
              <Button type="submit" disabled={promoteMutation.isPending || environmentsQuery.data?.length === 0}>
                {promoteMutation.isPending ? "Promoting…" : "Promote"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
