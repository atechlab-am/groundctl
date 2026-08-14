import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2, UploadCloud } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { RoleGate } from "@/layout/RoleGate";
import {
  getContentView,
  listContentViewVersions,
  listContentViewFilters,
  createContentViewFilter,
  deleteContentViewFilter,
  deleteContentView,
  publishContentView,
  type FilterType,
} from "@/api/contentViews";
import { listRepositories } from "@/api/repositories";
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

  const publishMutation = useMutation({
    mutationFn: () => publishContentView(contentViewId),
    onSuccess: (result) => {
      toast.success(
        result.version_cut
          ? `Published version ${result.content_view_version.version}`
          : `No content changes — version ${result.content_view_version.version} is still current`,
      );
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
                      {publishMutation.isPending ? "Publishing…" : "Publish"}
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
                    {versionsQuery.data?.map((v) => (
                      <li key={v.id} className="py-3">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">Version {v.version}</span>
                          <span className="text-xs text-muted-foreground">{formatDateTime(v.published_at)}</span>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {v.snapshots.map((s) => (
                            <Badge key={`${s.repository_id}-${s.component}`} variant="outline">
                              {s.repository_name}/{s.component}
                            </Badge>
                          ))}
                        </div>
                        <p className="mt-1 truncate text-xs text-muted-foreground" title={v.content_hash}>
                          hash: {v.content_hash}
                        </p>
                      </li>
                    ))}
                  </ul>
                </QueryState>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>
    </div>
  );
}
