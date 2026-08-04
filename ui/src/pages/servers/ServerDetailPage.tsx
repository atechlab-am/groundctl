import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, PowerOff, MapPin, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { getServer, getLatestServerFacts, getServerFactsHistory, decommissionServer, assignServerSite } from "@/api/servers";
import { listJobs } from "@/api/jobs";
import { checkServerCompliance } from "@/api/compliance";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function ServerDetailPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [siteDialogOpen, setSiteDialogOpen] = useState(false);
  const [siteId, setSiteId] = useState("");

  if (!serverId) return null;

  const serverQuery = useQuery({ queryKey: ["server", serverId], queryFn: () => getServer(serverId) });
  const factsQuery = useQuery({
    queryKey: ["server-facts", serverId],
    queryFn: () => getLatestServerFacts(serverId),
    retry: false,
  });
  const factsHistoryQuery = useQuery({
    queryKey: ["server-facts-history", serverId],
    queryFn: () => getServerFactsHistory(serverId, { limit: 20 }),
  });
  const jobsQuery = useQuery({
    queryKey: ["jobs", "server", serverId],
    queryFn: () => listJobs({ server_id: serverId, limit: 50 }),
  });

  const decommissionMutation = useMutation({
    mutationFn: () => decommissionServer(serverId),
    onSuccess: () => {
      toast.success("Server decommissioned");
      void queryClient.invalidateQueries({ queryKey: ["server", serverId] });
      void queryClient.invalidateQueries({ queryKey: ["servers"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const assignSiteMutation = useMutation({
    mutationFn: (id: string | null) => assignServerSite(serverId, id),
    onSuccess: () => {
      toast.success("Site updated");
      void queryClient.invalidateQueries({ queryKey: ["server", serverId] });
      setSiteDialogOpen(false);
      setSiteId("");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const complianceMutation = useMutation({
    mutationFn: () => checkServerCompliance(serverId),
    onSuccess: (result) => {
      const outdated = result.drift.filter((d) => d.status === "outdated").length;
      toast.success(outdated > 0 ? `${outdated} outdated package(s) found` : "All packages up to date");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/servers")}>
        <ArrowLeft className="h-4 w-4" />
        Back to servers
      </Button>

      <QueryState isLoading={serverQuery.isLoading} isError={serverQuery.isError} error={serverQuery.error}>
        {serverQuery.data && (
          <>
            <PageHeader
              title={serverQuery.data.hostname}
              description={serverQuery.data.ip_address}
              actions={
                <RoleGate minRole="operator">
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={complianceMutation.isPending}
                      onClick={() => complianceMutation.mutate()}
                    >
                      <ShieldCheck className="h-4 w-4" />
                      Check compliance
                    </Button>
                    <Dialog open={siteDialogOpen} onOpenChange={setSiteDialogOpen}>
                      <DialogTrigger asChild>
                        <Button variant="outline" size="sm">
                          <MapPin className="h-4 w-4" />
                          Assign site
                        </Button>
                      </DialogTrigger>
                      <DialogContent>
                        <DialogHeader>
                          <DialogTitle>Assign site</DialogTitle>
                          <DialogDescription>Leave blank to unassign.</DialogDescription>
                        </DialogHeader>
                        <div className="mt-4 flex flex-col gap-1.5">
                          <Input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site uuid" />
                        </div>
                        <DialogFooter className="mt-6">
                          <Button
                            disabled={assignSiteMutation.isPending}
                            onClick={() => assignSiteMutation.mutate(siteId || null)}
                          >
                            Save
                          </Button>
                        </DialogFooter>
                      </DialogContent>
                    </Dialog>
                    {serverQuery.data.lifecycle_state === "active" && (
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={decommissionMutation.isPending}
                        onClick={() => {
                          if (confirm("Decommission this server?")) decommissionMutation.mutate();
                        }}
                      >
                        <PowerOff className="h-4 w-4" />
                        Decommission
                      </Button>
                    )}
                  </div>
                </RoleGate>
              }
            />

            <div className="mb-6 flex flex-wrap gap-2">
              <StatusBadge value={serverQuery.data.status} />
              <StatusBadge value={serverQuery.data.lifecycle_state} />
              <Badge variant="outline">SSH: {serverQuery.data.ssh_user}</Badge>
            </div>

            <Tabs defaultValue="facts">
              <TabsList>
                <TabsTrigger value="facts">Facts</TabsTrigger>
                <TabsTrigger value="history">Facts history</TabsTrigger>
                <TabsTrigger value="jobs">Jobs</TabsTrigger>
              </TabsList>

              <TabsContent value="facts">
                <Card>
                  <CardContent className="p-5">
                    {factsQuery.isLoading ? (
                      <p className="text-sm text-muted-foreground">Loading…</p>
                    ) : factsQuery.isError ? (
                      <p className="text-sm text-muted-foreground">
                        No facts gathered yet — trigger a gather-facts job from the Jobs page.
                      </p>
                    ) : factsQuery.data ? (
                      <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
                        <FactItem label="OS" value={factsQuery.data.os_distribution ?? "—"} />
                        <FactItem label="OS version" value={factsQuery.data.os_version ?? "—"} />
                        <FactItem label="Kernel" value={factsQuery.data.kernel ?? "—"} />
                        <FactItem label="Uptime" value={formatUptime(factsQuery.data.uptime_seconds)} />
                        <FactItem label="Gathered" value={formatDateTime(factsQuery.data.gathered_at)} />
                        <FactItem label="Disks" value={String(factsQuery.data.disk.length)} />
                        <FactItem label="Services" value={String(factsQuery.data.services.length)} />
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="history">
                <QueryState
                  isLoading={factsHistoryQuery.isLoading}
                  isError={factsHistoryQuery.isError}
                  error={factsHistoryQuery.error}
                  isEmpty={factsHistoryQuery.data?.length === 0}
                  emptyMessage="No facts history yet."
                >
                  <ul className="flex flex-col divide-y rounded-lg border">
                    {factsHistoryQuery.data?.map((fact, i) => (
                      <li key={i} className="flex items-center justify-between px-4 py-2 text-sm">
                        <span>
                          {fact.os_distribution ?? "unknown"} {fact.os_version ?? ""}
                        </span>
                        <span className="text-muted-foreground">{formatDateTime(fact.gathered_at)}</span>
                      </li>
                    ))}
                  </ul>
                </QueryState>
              </TabsContent>

              <TabsContent value="jobs">
                <QueryState
                  isLoading={jobsQuery.isLoading}
                  isError={jobsQuery.isError}
                  error={jobsQuery.error}
                  isEmpty={jobsQuery.data?.length === 0}
                  emptyMessage="No jobs have targeted this server."
                >
                  <ul className="flex flex-col divide-y rounded-lg border">
                    {jobsQuery.data?.map((job) => (
                      <li key={job.id} className="flex items-center justify-between px-4 py-2 text-sm">
                        <Link to={`/jobs/${job.id}`} className="font-medium hover:underline">
                          {job.job_type}
                        </Link>
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">{formatDateTime(job.created_at)}</span>
                          <StatusBadge value={job.status} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </QueryState>
              </TabsContent>
            </Tabs>
          </>
        )}
      </QueryState>
    </div>
  );
}

function FactItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
