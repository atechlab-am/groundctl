import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Plus, Save } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
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
import {
  getSite,
  updateSite,
  getRelay,
  createRelay,
  listSiteEnvironments,
  replaceSiteEnvironments,
  type RelayCreate,
} from "@/api/sites";
import { listLifecycleEnvironments } from "@/api/environments";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, formatBytes } from "@/lib/format";

export function SiteDetailPage() {
  const { siteId } = useParams<{ siteId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [relayDialogOpen, setRelayDialogOpen] = useState(false);
  const [relayForm, setRelayForm] = useState<RelayCreate>({ hostname: "", ssh_user: "" });
  const [relayError, setRelayError] = useState<string | null>(null);
  const [selectedEnvIds, setSelectedEnvIds] = useState<Set<string>>(new Set());
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  if (!siteId) return null;

  const siteQuery = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId) });
  const relayQuery = useQuery({
    queryKey: ["site-relay", siteId],
    queryFn: () => getRelay(siteId),
    retry: false,
  });
  const siteEnvironmentsQuery = useQuery({
    queryKey: ["site-environments", siteId],
    queryFn: () => listSiteEnvironments(siteId, { limit: 100 }),
  });
  const allEnvironmentsQuery = useQuery({
    queryKey: ["environments", "for-site"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });

  useEffect(() => {
    if (siteEnvironmentsQuery.data) {
      setSelectedEnvIds(new Set(siteEnvironmentsQuery.data.map((e) => e.id)));
    }
  }, [siteEnvironmentsQuery.data]);

  function openEdit() {
    if (!siteQuery.data) return;
    setEditName(siteQuery.data.name);
    setEditDescription(siteQuery.data.description ?? "");
    setEditError(null);
    setEditDialogOpen(true);
  }

  const updateSiteMutation = useMutation({
    mutationFn: () => updateSite(siteId, { name: editName, description: editDescription || null }),
    onSuccess: () => {
      toast.success("Site updated");
      void queryClient.invalidateQueries({ queryKey: ["site", siteId] });
      void queryClient.invalidateQueries({ queryKey: ["sites"] });
      setEditDialogOpen(false);
    },
    onError: (err) => setEditError(errorMessage(err)),
  });

  const createRelayMutation = useMutation({
    mutationFn: (payload: RelayCreate) => createRelay(siteId, payload),
    onSuccess: () => {
      toast.success("Relay registered");
      void queryClient.invalidateQueries({ queryKey: ["site-relay", siteId] });
      setRelayDialogOpen(false);
      setRelayForm({ hostname: "", ssh_user: "" });
      setRelayError(null);
    },
    onError: (err) => setRelayError(errorMessage(err)),
  });

  const saveEnvironmentsMutation = useMutation({
    mutationFn: () => replaceSiteEnvironments(siteId, { environment_ids: Array.from(selectedEnvIds) }),
    onSuccess: () => {
      toast.success("Synced environments updated");
      void queryClient.invalidateQueries({ queryKey: ["site-environments", siteId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleRelaySubmit(e: FormEvent) {
    e.preventDefault();
    setRelayError(null);
    createRelayMutation.mutate(relayForm);
  }

  function toggleEnv(id: string) {
    setSelectedEnvIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/sites")}>
        <ArrowLeft className="h-4 w-4" />
        Back to sites
      </Button>

      <QueryState isLoading={siteQuery.isLoading} isError={siteQuery.isError} error={siteQuery.error}>
        {siteQuery.data && (
          <>
            <PageHeader
              title={siteQuery.data.name}
              description={siteQuery.data.description ?? undefined}
              actions={
                <RoleGate minRole="operator">
                  <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
                    <DialogTrigger asChild>
                      <Button size="sm" variant="outline" onClick={openEdit}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          setEditError(null);
                          updateSiteMutation.mutate();
                        }}
                      >
                        <DialogHeader>
                          <DialogTitle>Edit site</DialogTitle>
                        </DialogHeader>
                        <div className="mt-4 flex flex-col gap-4">
                          {editError && <p className="text-sm text-destructive">{editError}</p>}
                          <div className="flex flex-col gap-1.5">
                            <Label htmlFor="site-name">Name</Label>
                            <Input id="site-name" value={editName} onChange={(e) => setEditName(e.target.value)} required />
                          </div>
                          <div className="flex flex-col gap-1.5">
                            <Label htmlFor="site-description">Description</Label>
                            <Textarea
                              id="site-description"
                              value={editDescription}
                              onChange={(e) => setEditDescription(e.target.value)}
                              placeholder="Optional"
                            />
                          </div>
                        </div>
                        <DialogFooter className="mt-6">
                          <Button type="submit" disabled={updateSiteMutation.isPending}>
                            {updateSiteMutation.isPending ? "Saving…" : "Save"}
                          </Button>
                        </DialogFooter>
                      </form>
                    </DialogContent>
                  </Dialog>
                </RoleGate>
              }
            />

            <div className="mb-6">
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <CardTitle className="text-sm">Relay</CardTitle>
                  {relayQuery.isError && (
                    <RoleGate minRole="operator">
                      <Dialog open={relayDialogOpen} onOpenChange={setRelayDialogOpen}>
                        <DialogTrigger asChild>
                          <Button size="sm" variant="outline">
                            <Plus className="h-4 w-4" />
                            Register relay
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <form onSubmit={handleRelaySubmit}>
                            <DialogHeader>
                              <DialogTitle>Register relay</DialogTitle>
                              <DialogDescription>A site can have at most one relay.</DialogDescription>
                            </DialogHeader>
                            <div className="mt-4 flex flex-col gap-4">
                              {relayError && <p className="text-sm text-destructive">{relayError}</p>}
                              <div className="flex flex-col gap-1.5">
                                <Label htmlFor="relay-hostname">Hostname</Label>
                                <Input
                                  id="relay-hostname"
                                  value={relayForm.hostname}
                                  onChange={(e) => setRelayForm((f) => ({ ...f, hostname: e.target.value }))}
                                  required
                                />
                              </div>
                              <div className="flex flex-col gap-1.5">
                                <Label htmlFor="relay-user">SSH user</Label>
                                <Input
                                  id="relay-user"
                                  value={relayForm.ssh_user}
                                  onChange={(e) => setRelayForm((f) => ({ ...f, ssh_user: e.target.value }))}
                                  required
                                />
                              </div>
                            </div>
                            <DialogFooter className="mt-6">
                              <Button type="submit" disabled={createRelayMutation.isPending}>
                                {createRelayMutation.isPending ? "Registering…" : "Register"}
                              </Button>
                            </DialogFooter>
                          </form>
                        </DialogContent>
                      </Dialog>
                    </RoleGate>
                  )}
                </CardHeader>
                <CardContent>
                  {relayQuery.isLoading ? (
                    <p className="text-sm text-muted-foreground">Loading…</p>
                  ) : relayQuery.isError ? (
                    <p className="text-sm text-muted-foreground">This site has no relay yet.</p>
                  ) : relayQuery.data ? (
                    <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
                      <div>
                        <p className="text-xs text-muted-foreground">Hostname</p>
                        <p className="font-medium">{relayQuery.data.hostname}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Sync status</p>
                        <StatusBadge value={relayQuery.data.sync_status} />
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Last synced</p>
                        <p className="font-medium">{formatDateTime(relayQuery.data.last_sync_time)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Content size</p>
                        <p className="font-medium">{formatBytes(relayQuery.data.content_size_bytes)}</p>
                      </div>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-sm">Synced environments</CardTitle>
                  <CardDescription>Which lifecycle environments this site's relay should carry.</CardDescription>
                </div>
                <RoleGate minRole="operator">
                  <Button size="sm" disabled={saveEnvironmentsMutation.isPending} onClick={() => saveEnvironmentsMutation.mutate()}>
                    <Save className="h-4 w-4" />
                    {saveEnvironmentsMutation.isPending ? "Saving…" : "Save"}
                  </Button>
                </RoleGate>
              </CardHeader>
              <CardContent>
                <QueryState
                  isLoading={allEnvironmentsQuery.isLoading}
                  isError={allEnvironmentsQuery.isError}
                  error={allEnvironmentsQuery.error}
                  isEmpty={allEnvironmentsQuery.data?.length === 0}
                  emptyMessage="No lifecycle environments exist yet."
                >
                  <div className="rounded-md border">
                    {allEnvironmentsQuery.data?.map((env) => (
                      <label
                        key={env.id}
                        className="flex items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0 hover:bg-accent"
                      >
                        <Checkbox checked={selectedEnvIds.has(env.id)} onCheckedChange={() => toggleEnv(env.id)} />
                        <span className="font-medium">{env.name}</span>
                        <span className="text-muted-foreground">{env.publish_prefix}</span>
                      </label>
                    ))}
                  </div>
                </QueryState>
              </CardContent>
            </Card>
          </>
        )}
      </QueryState>
    </div>
  );
}
