import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { Badge } from "@/components/ui/badge";
import { RoleGate } from "@/layout/RoleGate";
import { listRepositories, createRepository, syncRepository, type RepositoryCreate } from "@/api/repositories";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/errors";

const EMPTY_FORM: RepositoryCreate = {
  name: "",
  archive_url: "",
  distribution: "",
  components: [],
  architectures: [],
};

export function RepositoriesPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<RepositoryCreate>(EMPTY_FORM);
  const [componentsInput, setComponentsInput] = useState("");
  const [architecturesInput, setArchitecturesInput] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const repositoriesQuery = useQuery({ queryKey: ["repositories"], queryFn: () => listRepositories({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: (payload: RepositoryCreate) => createRepository(payload),
    onSuccess: () => {
      toast.success("Repository created");
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setComponentsInput("");
      setArchitecturesInput("");
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const syncMutation = useMutation({
    mutationFn: (name: string) => syncRepository(name),
    onSuccess: (repo) => {
      toast.success(`Sync triggered for ${repo.name}`);
      void queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate({
      ...form,
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
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New repository
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create repository</DialogTitle>
                    <DialogDescription>
                      Creates an aptly mirror of an upstream archive. Names must match{" "}
                      <code className="text-xs">^[a-zA-Z0-9._-]+$</code>.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="repo-name">Name</Label>
                      <Input
                        id="repo-name"
                        value={form.name}
                        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                        placeholder="jammy-main"
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="repo-url">Archive URL</Label>
                      <Input
                        id="repo-url"
                        type="url"
                        value={form.archive_url}
                        onChange={(e) => setForm((f) => ({ ...f, archive_url: e.target.value }))}
                        placeholder="http://archive.ubuntu.com/ubuntu"
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="repo-distribution">Distribution</Label>
                      <Input
                        id="repo-distribution"
                        value={form.distribution}
                        onChange={(e) => setForm((f) => ({ ...f, distribution: e.target.value }))}
                        placeholder="jammy"
                        required
                      />
                    </div>
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
              <TableHead>Distribution</TableHead>
              <TableHead>Components</TableHead>
              <TableHead>Architectures</TableHead>
              <TableHead>Last synced</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {repositoriesQuery.data?.map((repo) => (
              <TableRow key={repo.id}>
                <TableCell className="font-medium">{repo.name}</TableCell>
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
                <TableCell className="text-muted-foreground">{formatDateTime(repo.last_synced_at)}</TableCell>
                <TableCell className="text-right">
                  <RoleGate minRole="operator">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={syncMutation.isPending && syncMutation.variables === repo.name}
                      onClick={() => syncMutation.mutate(repo.name)}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Sync
                    </Button>
                  </RoleGate>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
