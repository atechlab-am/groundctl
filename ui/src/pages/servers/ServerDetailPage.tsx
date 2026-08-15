import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, PowerOff, MapPin, Route, ShieldCheck, Radio, Trash2, Copy } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
import {
  getServer,
  getLatestServerFacts,
  getServerFactsHistory,
  decommissionServer,
  assignServerSite,
  assignServerEnvironment,
  getBeaconState,
  listBeaconTokens,
  issueBeaconToken,
  revokeBeaconToken,
} from "@/api/servers";
import { listLifecycleEnvironments } from "@/api/environments";
import { listJobs, triggerInstallBeacon } from "@/api/jobs";
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
  const [envDialogOpen, setEnvDialogOpen] = useState(false);
  const [targetEnvironmentId, setTargetEnvironmentId] = useState("");
  const [envReason, setEnvReason] = useState("");

  if (!serverId) return null;

  const serverQuery = useQuery({ queryKey: ["server", serverId], queryFn: () => getServer(serverId) });
  const environmentsQuery = useQuery({
    queryKey: ["lifecycle-environments"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
    enabled: envDialogOpen,
  });
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

  const assignEnvironmentMutation = useMutation({
    mutationFn: () => assignServerEnvironment(serverId, targetEnvironmentId, envReason || undefined),
    onSuccess: () => {
      toast.success(
        "Environment updated — the host picks up the new apt source on its next bootstrap or beacon checkin",
      );
      void queryClient.invalidateQueries({ queryKey: ["server", serverId] });
      setEnvDialogOpen(false);
      setTargetEnvironmentId("");
      setEnvReason("");
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

  const beaconStateQuery = useQuery({
    queryKey: ["beacon-state", serverId],
    queryFn: () => getBeaconState(serverId),
    retry: false,
  });
  const beaconTokensQuery = useQuery({
    queryKey: ["beacon-tokens", serverId],
    queryFn: () => listBeaconTokens(serverId),
  });

  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [tokenNameInput, setTokenNameInput] = useState("");
  const issueTokenMutation = useMutation({
    mutationFn: () => issueBeaconToken(serverId, tokenNameInput || undefined),
    onSuccess: (result) => {
      setIssuedToken(result.token);
      setTokenNameInput("");
      void queryClient.invalidateQueries({ queryKey: ["beacon-tokens", serverId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const revokeTokenMutation = useMutation({
    mutationFn: (tokenId: string) => revokeBeaconToken(serverId, tokenId),
    onSuccess: () => {
      toast.success("Token revoked");
      void queryClient.invalidateQueries({ queryKey: ["beacon-tokens", serverId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const installBeaconMutation = useMutation({
    mutationFn: () => triggerInstallBeacon(serverId),
    onSuccess: (job) => {
      toast.success("Beacon install job triggered");
      navigate(`/jobs/${job.id}`);
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
                    <Dialog open={envDialogOpen} onOpenChange={setEnvDialogOpen}>
                      <DialogTrigger asChild>
                        <Button variant="outline" size="sm">
                          <Route className="h-4 w-4" />
                          Assign environment
                        </Button>
                      </DialogTrigger>
                      <DialogContent>
                        <DialogHeader>
                          <DialogTitle>Assign environment</DialogTitle>
                          <DialogDescription>
                            Changing this alone doesn't move any packages — the host only starts pulling from the
                            new environment once it re-bootstraps or, once deployed, its next beacon checkin.
                          </DialogDescription>
                        </DialogHeader>
                        <div className="mt-4 flex flex-col gap-4">
                          <div className="flex flex-col gap-1.5">
                            <Label>Environment</Label>
                            <Select value={targetEnvironmentId} onValueChange={setTargetEnvironmentId}>
                              <SelectTrigger>
                                <SelectValue placeholder="Select an environment" />
                              </SelectTrigger>
                              <SelectContent>
                                {environmentsQuery.data?.map((env) => (
                                  <SelectItem key={env.id} value={env.id}>
                                    {env.name} ({env.path_name}, position {env.position})
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="flex flex-col gap-1.5">
                            <Label htmlFor="env-reassign-reason">Reason (optional)</Label>
                            <Input
                              id="env-reassign-reason"
                              value={envReason}
                              onChange={(e) => setEnvReason(e.target.value)}
                            />
                          </div>
                        </div>
                        <DialogFooter className="mt-6">
                          <Button
                            disabled={assignEnvironmentMutation.isPending || !targetEnvironmentId}
                            onClick={() => assignEnvironmentMutation.mutate()}
                          >
                            {assignEnvironmentMutation.isPending ? "Saving…" : "Save"}
                          </Button>
                        </DialogFooter>
                      </DialogContent>
                    </Dialog>
                    {!beaconStateQuery.data && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={installBeaconMutation.isPending}
                        onClick={() => installBeaconMutation.mutate()}
                      >
                        <Radio className="h-4 w-4" />
                        Install Beacon
                      </Button>
                    )}
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
              {beaconStateQuery.data && (
                <Badge variant={beaconStateQuery.data.pending_reconciliation ? "warning" : "success"}>
                  <Radio className="h-3 w-3" />
                  {beaconStateQuery.data.pending_reconciliation ? "Beacon: pending reconciliation" : "Beacon: in sync"}
                </Badge>
              )}
            </div>

            <Tabs defaultValue="facts">
              <TabsList>
                <TabsTrigger value="facts">Facts</TabsTrigger>
                <TabsTrigger value="history">Facts history</TabsTrigger>
                <TabsTrigger value="jobs">Jobs</TabsTrigger>
                <TabsTrigger value="beacon">Beacon</TabsTrigger>
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

              <TabsContent value="beacon">
                <Card>
                  <CardContent className="flex flex-col gap-6 p-5">
                    {beaconStateQuery.isLoading ? (
                      <p className="text-sm text-muted-foreground">Loading…</p>
                    ) : beaconStateQuery.isError ? (
                      <p className="text-sm text-muted-foreground">
                        This server isn't beacon-managed yet — install Beacon to enable pull-based checkins.
                      </p>
                    ) : beaconStateQuery.data ? (
                      <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
                        <FactItem label="Config serial" value={String(beaconStateQuery.data.config_serial)} />
                        <FactItem
                          label="Applied serial"
                          value={
                            beaconStateQuery.data.applied_config_serial === null
                              ? "never"
                              : String(beaconStateQuery.data.applied_config_serial)
                          }
                        />
                        <FactItem label="Last checkin" value={formatDateTime(beaconStateQuery.data.last_checkin_at)} />
                        <FactItem label="Last apply" value={beaconStateQuery.data.last_apply_status ?? "—"} />
                        <FactItem label="Agent version" value={beaconStateQuery.data.agent_version ?? "—"} />
                        <FactItem
                          label="Last facts push"
                          value={formatDateTime(beaconStateQuery.data.last_facts_pushed_at)}
                        />
                      </div>
                    ) : null}

                    <div>
                      <div className="mb-2 flex items-center justify-between">
                        <Label className="text-sm">Tokens</Label>
                        <RoleGate minRole="operator">
                          <Dialog
                            onOpenChange={(open) => {
                              if (!open) setIssuedToken(null);
                            }}
                          >
                            <DialogTrigger asChild>
                              <Button variant="outline" size="sm">
                                Issue token
                              </Button>
                            </DialogTrigger>
                            <DialogContent>
                              <DialogHeader>
                                <DialogTitle>Issue Beacon token</DialogTitle>
                                <DialogDescription>
                                  Shown once — copy it now. Groundctl only ever stores its hash.
                                </DialogDescription>
                              </DialogHeader>
                              {issuedToken ? (
                                <div className="mt-4 flex flex-col gap-2">
                                  <div className="flex items-center gap-2 rounded-md border bg-muted p-2 font-mono text-xs break-all">
                                    {issuedToken}
                                  </div>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                      void navigator.clipboard.writeText(issuedToken);
                                      toast.success("Copied to clipboard");
                                    }}
                                  >
                                    <Copy className="h-4 w-4" />
                                    Copy
                                  </Button>
                                </div>
                              ) : (
                                <>
                                  <div className="mt-4 flex flex-col gap-1.5">
                                    <Label htmlFor="beacon-token-name">Name (optional)</Label>
                                    <Input
                                      id="beacon-token-name"
                                      value={tokenNameInput}
                                      onChange={(e) => setTokenNameInput(e.target.value)}
                                    />
                                  </div>
                                  <DialogFooter className="mt-6">
                                    <Button
                                      disabled={issueTokenMutation.isPending}
                                      onClick={() => issueTokenMutation.mutate()}
                                    >
                                      {issueTokenMutation.isPending ? "Issuing…" : "Issue"}
                                    </Button>
                                  </DialogFooter>
                                </>
                              )}
                            </DialogContent>
                          </Dialog>
                        </RoleGate>
                      </div>
                      <QueryState
                        isLoading={beaconTokensQuery.isLoading}
                        isError={beaconTokensQuery.isError}
                        error={beaconTokensQuery.error}
                        isEmpty={beaconTokensQuery.data?.length === 0}
                        emptyMessage="No tokens issued yet."
                      >
                        <ul className="flex flex-col divide-y rounded-lg border">
                          {beaconTokensQuery.data?.map((token) => (
                            <li key={token.id} className="flex items-center justify-between px-4 py-2 text-sm">
                              <div className="flex items-center gap-2">
                                <span className="font-medium">{token.name ?? "(unnamed)"}</span>
                                {token.revoked && <Badge variant="destructive">Revoked</Badge>}
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-muted-foreground">
                                  last used {formatDateTime(token.last_used_at)}
                                </span>
                                {!token.revoked && (
                                  <RoleGate minRole="operator">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      disabled={revokeTokenMutation.isPending}
                                      onClick={() => {
                                        if (confirm("Revoke this Beacon token?")) revokeTokenMutation.mutate(token.id);
                                      }}
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </RoleGate>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </QueryState>
                    </div>
                  </CardContent>
                </Card>
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
