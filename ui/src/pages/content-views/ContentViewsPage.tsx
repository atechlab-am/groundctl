import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { RoleGate } from "@/layout/RoleGate";
import { createContentView, listContentViews, type ContentViewCreate } from "@/api/contentViews";
import { listRepositories } from "@/api/repositories";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

export function ContentViewsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const contentViewsQuery = useQuery({
    queryKey: ["content-views"],
    queryFn: () => listContentViews({ limit: 100 }),
  });

  const repositoriesQuery = useQuery({ queryKey: ["repositories"], queryFn: () => listRepositories({ limit: 100 }) });
  const repoNameById = new Map((repositoriesQuery.data ?? []).map((r) => [r.id, r.name]));

  const createMutation = useMutation({
    mutationFn: (payload: ContentViewCreate) => createContentView(payload),
    onSuccess: (view) => {
      toast.success(`Content view "${view.name}" created`);
      void queryClient.invalidateQueries({ queryKey: ["content-views"] });
      setDialogOpen(false);
      setName("");
      setDescription("");
      setSelectedRepoIds([]);
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  function toggleRepo(id: string) {
    setSelectedRepoIds((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (selectedRepoIds.length === 0) {
      setFormError("select at least one repository");
      return;
    }
    createMutation.mutate({
      name,
      description: description.trim() || null,
      repository_ids: selectedRepoIds,
    });
  }

  return (
    <div>
      <PageHeader
        title="Content Views"
        description="Named, filterable bundles of repositories that get versioned and promoted"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New content view
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create content view</DialogTitle>
                    <DialogDescription>
                      Bundle one or more repositories into a versioned content view. Version 1 is cut immediately
                      from the selected repositories' current package state.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="cv-name">Name</Label>
                      <Input id="cv-name" value={name} onChange={(e) => setName(e.target.value)} required />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="cv-description">Description (optional)</Label>
                      <Textarea
                        id="cv-description"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={2}
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>Repositories</Label>
                      <div className="max-h-52 overflow-y-auto rounded-md border p-2">
                        {repositoriesQuery.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
                        {repositoriesQuery.data?.length === 0 && (
                          <p className="text-sm text-muted-foreground">No repositories exist yet — create one first.</p>
                        )}
                        {repositoriesQuery.data?.map((repo) => (
                          <label key={repo.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent">
                            <Checkbox
                              checked={selectedRepoIds.includes(repo.id)}
                              onCheckedChange={() => toggleRepo(repo.id)}
                            />
                            {repo.name}
                            <span className="text-xs text-muted-foreground">({repo.distribution})</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                  <DialogFooter className="mt-6">
                    <Button type="submit" disabled={createMutation.isPending}>
                      {createMutation.isPending ? "Creating…" : "Create"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </RoleGate>
        }
      />

      <QueryState
        isLoading={contentViewsQuery.isLoading}
        isError={contentViewsQuery.isError}
        error={contentViewsQuery.error}
        isEmpty={contentViewsQuery.data?.length === 0}
        emptyMessage="No content views yet. Create one to bundle repositories for promotion."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Repositories</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {contentViewsQuery.data?.map((view) => (
              <TableRow key={view.id}>
                <TableCell className="font-medium">
                  <Link to={`/content-views/${view.id}`} className="hover:underline">
                    {view.name}
                  </Link>
                </TableCell>
                <TableCell className="max-w-64 truncate text-muted-foreground" title={view.description ?? undefined}>
                  {view.description || "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {view.repository_ids.length === 0
                    ? "—"
                    : view.repository_ids.map((id) => repoNameById.get(id) ?? id).join(", ")}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(view.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
