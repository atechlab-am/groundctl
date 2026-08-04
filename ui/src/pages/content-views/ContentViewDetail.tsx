import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, UploadCloud } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { QueryState } from "@/components/QueryState";
import { RoleGate } from "@/layout/RoleGate";
import {
  listContentViewVersions,
  createContentViewFilter,
  publishContentView,
  type ContentViewRead,
  type FilterType,
} from "@/api/contentViews";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

export function ContentViewDetail({ view, onPublished }: { view: ContentViewRead; onPublished: () => void }) {
  const queryClient = useQueryClient();
  const [filterType, setFilterType] = useState<FilterType>("include");
  const [pattern, setPattern] = useState("");
  const [filterError, setFilterError] = useState<string | null>(null);

  const versionsQuery = useQuery({
    queryKey: ["content-view-versions", view.id],
    queryFn: () => listContentViewVersions(view.id, { limit: 50 }),
  });

  const filterMutation = useMutation({
    mutationFn: () => createContentViewFilter(view.id, { filter_type: filterType, pattern }),
    onSuccess: () => {
      toast.success("Filter added");
      setPattern("");
      setFilterError(null);
    },
    onError: (err) => setFilterError(errorMessage(err)),
  });

  const publishMutation = useMutation({
    mutationFn: () => publishContentView(view.id),
    onSuccess: (result) => {
      toast.success(
        result.version_cut
          ? `Published version ${result.content_view_version.version}`
          : `No content changes — version ${result.content_view_version.version} is still current`,
      );
      void queryClient.invalidateQueries({ queryKey: ["content-view-versions", view.id] });
      onPublished();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleAddFilter(e: FormEvent) {
    e.preventDefault();
    setFilterError(null);
    filterMutation.mutate();
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex-row items-start justify-between">
          <div>
            <CardTitle>{view.name}</CardTitle>
            <CardDescription>{view.repository_ids.length} repositories</CardDescription>
          </div>
          <RoleGate minRole="operator">
            <Button size="sm" onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending}>
              <UploadCloud className="h-4 w-4" />
              {publishMutation.isPending ? "Publishing…" : "Publish"}
            </Button>
          </RoleGate>
        </CardHeader>
      </Card>

      <RoleGate minRole="operator">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Add filter</CardTitle>
            <CardDescription>Include/exclude packages by pattern, or scope to errata since a date.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAddFilter} className="flex flex-col gap-3 sm:flex-row sm:items-end">
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
          </CardContent>
        </Card>
      </RoleGate>

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
  );
}
