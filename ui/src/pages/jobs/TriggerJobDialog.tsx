import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useHasRole } from "@/auth/useHasRole";
import {
  triggerBootstrap,
  triggerApplyUpdates,
  triggerGatherFacts,
  triggerBulkApplyUpdates,
  triggerRunCommand,
  triggerManagePackage,
  type JobType,
  type PackageAction,
} from "@/api/jobs";
import { listHostGroups } from "@/api/hostGroups";
import { errorMessage } from "@/lib/errors";
import { titleCase } from "@/lib/format";

type TriggerableJobType = JobType;

const ALL_TYPES: TriggerableJobType[] = [
  "bootstrap",
  "apply_updates",
  "gather_facts",
  "bulk_apply_updates",
  "run_command",
  "manage_package",
];

export function TriggerJobDialog({ onDone }: { onDone: () => void }) {
  const isAdmin = useHasRole("admin");
  const availableTypes = ALL_TYPES.filter((t) => t !== "run_command" || isAdmin);
  const [jobType, setJobType] = useState<TriggerableJobType>("bootstrap");
  const [error, setError] = useState<string | null>(null);

  // Shared target fields for bootstrap/manage-package (single server) and
  // apply-updates/gather-facts (single environment).
  const [serverId, setServerId] = useState("");
  const [environmentId, setEnvironmentId] = useState("");

  // Shared bulk target selector for bulk-apply-updates/run-command.
  const [targetMode, setTargetMode] = useState<"host_group" | "server_ids">("host_group");
  const [hostGroupId, setHostGroupId] = useState("");
  const [serverIdsInput, setServerIdsInput] = useState("");
  const [command, setCommand] = useState("");

  const [packageName, setPackageName] = useState("");
  const [packageAction, setPackageAction] = useState<PackageAction>("install");

  const hostGroupsQuery = useQuery({
    queryKey: ["host-groups", "trigger-job"],
    queryFn: () => listHostGroups({ limit: 100 }),
    enabled: jobType === "bulk_apply_updates" || jobType === "run_command",
  });

  const mutation = useMutation({
    mutationFn: async () => {
      switch (jobType) {
        case "bootstrap":
          return triggerBootstrap(serverId);
        case "apply_updates":
          return triggerApplyUpdates(environmentId);
        case "gather_facts":
          return triggerGatherFacts(environmentId);
        case "bulk_apply_updates":
          return triggerBulkApplyUpdates(buildSelector());
        case "run_command":
          return triggerRunCommand({ ...buildSelector(), command });
        case "manage_package":
          return triggerManagePackage({ server_id: serverId, package_name: packageName, action: packageAction });
      }
    },
    onSuccess: () => onDone(),
    onError: (err) => setError(errorMessage(err)),
  });

  function buildSelector() {
    if (targetMode === "host_group") {
      return { host_group_id: hostGroupId, server_ids: undefined };
    }
    return {
      host_group_id: undefined,
      server_ids: serverIdsInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  const needsBulkTarget = jobType === "bulk_apply_updates" || jobType === "run_command";

  return (
    <form onSubmit={handleSubmit}>
      <DialogHeader>
        <DialogTitle>Trigger job</DialogTitle>
        <DialogDescription>
          {jobType === "run_command" && "Admin-only — runs a literal command via ansible.builtin.command (no shell)."}
        </DialogDescription>
      </DialogHeader>

      <div className="mt-4 flex flex-col gap-4">
        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-col gap-1.5">
          <Label>Job type</Label>
          <Select value={jobType} onValueChange={(v) => setJobType(v as TriggerableJobType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {availableTypes.map((t) => (
                <SelectItem key={t} value={t}>
                  {titleCase(t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {(jobType === "bootstrap" || jobType === "manage_package") && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="job-server-id">Server ID</Label>
            <Input id="job-server-id" value={serverId} onChange={(e) => setServerId(e.target.value)} required />
          </div>
        )}

        {(jobType === "apply_updates" || jobType === "gather_facts") && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="job-env-id">Environment ID</Label>
            <Input id="job-env-id" value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)} required />
          </div>
        )}

        {jobType === "manage_package" && (
          <>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="job-pkg-name">Package name</Label>
              <Input id="job-pkg-name" value={packageName} onChange={(e) => setPackageName(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Action</Label>
              <Select value={packageAction} onValueChange={(v) => setPackageAction(v as PackageAction)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="install">Install</SelectItem>
                  <SelectItem value="remove">Remove</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </>
        )}

        {needsBulkTarget && (
          <>
            <div className="flex flex-col gap-1.5">
              <Label>Target by</Label>
              <Select value={targetMode} onValueChange={(v) => setTargetMode(v as "host_group" | "server_ids")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="host_group">Host group</SelectItem>
                  <SelectItem value="server_ids">Specific server IDs</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {targetMode === "host_group" ? (
              <div className="flex flex-col gap-1.5">
                <Label>Host group</Label>
                <Select value={hostGroupId} onValueChange={setHostGroupId}>
                  <SelectTrigger>
                    <SelectValue placeholder={hostGroupsQuery.isLoading ? "Loading…" : "Select a host group"} />
                  </SelectTrigger>
                  <SelectContent>
                    {hostGroupsQuery.data?.map((g) => (
                      <SelectItem key={g.id} value={g.id}>
                        {g.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="job-server-ids">Server IDs (comma-separated)</Label>
                <Input
                  id="job-server-ids"
                  value={serverIdsInput}
                  onChange={(e) => setServerIdsInput(e.target.value)}
                  required
                />
              </div>
            )}
          </>
        )}

        {jobType === "run_command" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="job-command">Command</Label>
            <Textarea
              id="job-command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="apt list --upgradable"
              required
            />
            <p className="text-xs text-muted-foreground">
              No shell metacharacters allowed (; | &amp; $ ` newlines &lt;&gt;) — runs via ansible.builtin.command, not a
              shell.
            </p>
          </div>
        )}
      </div>

      <DialogFooter className="mt-6">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Triggering…" : "Trigger"}
        </Button>
      </DialogFooter>
    </form>
  );
}
