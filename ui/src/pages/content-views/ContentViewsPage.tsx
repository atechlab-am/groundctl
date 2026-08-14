import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { createContentView, type ContentViewCreate } from "@/api/contentViews";
import { listRepositories } from "@/api/repositories";
import { errorMessage } from "@/lib/errors";
import { useKnownContentViews } from "./useKnownContentViews";
import { ContentViewDetail } from "./ContentViewDetail";

export function ContentViewsPage() {
  const queryClient = useQueryClient();
  const { views, remember } = useKnownContentViews();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedViewId, setSelectedViewId] = useState<string | null>(null);

  const repositoriesQuery = useQuery({ queryKey: ["repositories"], queryFn: () => listRepositories({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: (payload: ContentViewCreate) => createContentView(payload),
    onSuccess: (view) => {
      toast.success(`Content view "${view.name}" created`);
      remember(view);
      setSelectedViewId(view.id);
      setDialogOpen(false);
      setName("");
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
    createMutation.mutate({ name, repository_ids: selectedRepoIds });
  }

  const selectedView = views.find((v) => v.id === selectedViewId) ?? null;

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
                    <DialogDescription>Bundle one or more repositories into a versioned content view.</DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="cv-name">Name</Label>
                      <Input id="cv-name" value={name} onChange={(e) => setName(e.target.value)} required />
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

      <Alert className="mb-6">
        <AlertDescription>
          The backend has no endpoint to list all content views — only creation exists. This page tracks content
          views you've created in this browser session only.
        </AlertDescription>
      </Alert>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle>Known content views</CardTitle>
              <CardDescription>Created this session</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="border-b pb-3 text-xs text-muted-foreground">
                No backend endpoint lists all content views — only what this browser session has created appears
                here.
              </p>
              {views.length === 0 ? (
                <p className="text-sm text-muted-foreground">None yet.</p>
              ) : (
                <ul className="flex flex-col divide-y">
                  {views.map((v) => (
                    <li key={v.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedViewId(v.id)}
                        className={`w-full rounded px-2 py-2 text-left text-sm hover:bg-accent ${
                          selectedViewId === v.id ? "bg-accent font-medium" : ""
                        }`}
                      >
                        {v.name}
                        <div className="text-xs text-muted-foreground">{v.repository_ids.length} repositories</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          {selectedView ? (
            <ContentViewDetail
              view={selectedView}
              onPublished={() => void queryClient.invalidateQueries({ queryKey: ["content-view-versions", selectedView.id] })}
            />
          ) : (
            <Card>
              <CardContent className="p-8 text-center text-sm text-muted-foreground">
                Select a content view to view its versions, add filters, or publish.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

