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
import { listSites, createSite, type SiteCreate } from "@/api/sites";
import { errorMessage } from "@/lib/errors";

export function SitesPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<SiteCreate>({ name: "", description: "" });
  const [formError, setFormError] = useState<string | null>(null);

  const sitesQuery = useQuery({ queryKey: ["sites"], queryFn: () => listSites({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: (payload: SiteCreate) => createSite({ ...payload, description: payload.description || null }),
    onSuccess: () => {
      toast.success("Site created");
      void queryClient.invalidateQueries({ queryKey: ["sites"] });
      setDialogOpen(false);
      setForm({ name: "", description: "" });
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate(form);
  }

  return (
    <div>
      <PageHeader
        title="Sites"
        description="Physical/network locations, each servable by at most one relay"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New site
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create site</DialogTitle>
                    <DialogDescription>You can register a relay and configure synced environments after creating.</DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="site-name">Name</Label>
                      <Input id="site-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="site-desc">Description</Label>
                      <Input
                        id="site-desc"
                        value={form.description ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
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
        isLoading={sitesQuery.isLoading}
        isError={sitesQuery.isError}
        error={sitesQuery.error}
        isEmpty={sitesQuery.data?.length === 0}
        emptyMessage="No sites yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sitesQuery.data?.map((site) => (
              <TableRow key={site.id}>
                <TableCell className="font-medium">
                  <Link to={`/sites/${site.id}`} className="hover:underline">
                    {site.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{site.description ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
