import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
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
import { listServers, createServer, type ServerCreate } from "@/api/servers";
import { errorMessage } from "@/lib/errors";
import { formatRelativeToNow } from "@/lib/format";

const EMPTY_FORM: ServerCreate = {
  hostname: "",
  ip_address: "",
  ssh_user: "",
  environment_id: "",
};

export function ServersPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<ServerCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const serversQuery = useQuery({ queryKey: ["servers"], queryFn: () => listServers({ limit: 200 }) });

  const createMutation = useMutation({
    mutationFn: (payload: ServerCreate) => createServer(payload),
    onSuccess: () => {
      toast.success("Server registered");
      void queryClient.invalidateQueries({ queryKey: ["servers"] });
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
        title="Servers"
        description="Managed hosts across every lifecycle environment"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  Register server
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Register server</DialogTitle>
                    <DialogDescription>Requires the target lifecycle environment's UUID.</DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="srv-hostname">Hostname</Label>
                      <Input
                        id="srv-hostname"
                        value={form.hostname}
                        onChange={(e) => setForm((f) => ({ ...f, hostname: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="srv-ip">IP address</Label>
                      <Input
                        id="srv-ip"
                        value={form.ip_address}
                        onChange={(e) => setForm((f) => ({ ...f, ip_address: e.target.value }))}
                        placeholder="10.0.0.5"
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="srv-user">SSH user</Label>
                      <Input
                        id="srv-user"
                        value={form.ssh_user}
                        onChange={(e) => setForm((f) => ({ ...f, ssh_user: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="srv-env">Environment ID</Label>
                      <Input
                        id="srv-env"
                        value={form.environment_id}
                        onChange={(e) => setForm((f) => ({ ...f, environment_id: e.target.value }))}
                        placeholder="uuid"
                        required
                      />
                    </div>
                  </div>
                  <DialogFooter className="mt-6">
                    <Button type="submit" disabled={createMutation.isPending}>
                      {createMutation.isPending ? "Registering…" : "Register"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </RoleGate>
        }
      />

      <QueryState
        isLoading={serversQuery.isLoading}
        isError={serversQuery.isError}
        error={serversQuery.error}
        isEmpty={serversQuery.data?.length === 0}
        emptyMessage="No servers registered yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hostname</TableHead>
              <TableHead>IP address</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Lifecycle</TableHead>
              <TableHead>Last seen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {serversQuery.data?.map((server) => (
              <TableRow key={server.id}>
                <TableCell className="font-medium">
                  <Link to={`/servers/${server.id}`} className="hover:underline">
                    {server.hostname}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{server.ip_address}</TableCell>
                <TableCell>
                  <StatusBadge value={server.status} />
                </TableCell>
                <TableCell>
                  <StatusBadge value={server.lifecycle_state} />
                </TableCell>
                <TableCell className="text-muted-foreground">{formatRelativeToNow(server.last_seen_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
