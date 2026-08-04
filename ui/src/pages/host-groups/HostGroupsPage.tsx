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
import { listHostGroups, createHostGroup, type HostGroupCreate } from "@/api/hostGroups";
import { errorMessage } from "@/lib/errors";

const EMPTY_FORM: HostGroupCreate = { name: "", description: "", default_environment_id: "" };

export function HostGroupsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<HostGroupCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const groupsQuery = useQuery({ queryKey: ["host-groups"], queryFn: () => listHostGroups({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: (payload: HostGroupCreate) =>
      createHostGroup({
        ...payload,
        description: payload.description || null,
        default_environment_id: payload.default_environment_id || null,
      }),
    onSuccess: () => {
      toast.success("Host group created");
      void queryClient.invalidateQueries({ queryKey: ["host-groups"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
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
        title="Host Groups"
        description="Named collections of servers for bulk targeting"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New host group
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create host group</DialogTitle>
                    <DialogDescription>Optionally set a default environment for self-registering hosts.</DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="hg-name">Name</Label>
                      <Input id="hg-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="hg-desc">Description</Label>
                      <Input
                        id="hg-desc"
                        value={form.description ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="hg-env">Default environment ID (optional)</Label>
                      <Input
                        id="hg-env"
                        value={form.default_environment_id ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, default_environment_id: e.target.value }))}
                        placeholder="uuid"
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
        isLoading={groupsQuery.isLoading}
        isError={groupsQuery.isError}
        error={groupsQuery.error}
        isEmpty={groupsQuery.data?.length === 0}
        emptyMessage="No host groups yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groupsQuery.data?.map((g) => (
              <TableRow key={g.id}>
                <TableCell className="font-medium">
                  <Link to={`/host-groups/${g.id}`} className="hover:underline">
                    {g.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{g.description ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
