import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Save } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { RoleGate } from "@/layout/RoleGate";
import { getHostGroup, listHostGroupMembers, replaceHostGroupMembers } from "@/api/hostGroups";
import { listServers } from "@/api/servers";
import { errorMessage } from "@/lib/errors";

export function HostGroupDetailPage() {
  const { hostGroupId } = useParams<{ hostGroupId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  if (!hostGroupId) return null;

  const groupQuery = useQuery({ queryKey: ["host-group", hostGroupId], queryFn: () => getHostGroup(hostGroupId) });
  const membersQuery = useQuery({
    queryKey: ["host-group-members", hostGroupId],
    queryFn: () => listHostGroupMembers(hostGroupId, { limit: 200 }),
  });
  const allServersQuery = useQuery({ queryKey: ["servers", "for-host-group"], queryFn: () => listServers({ limit: 200 }) });

  useEffect(() => {
    if (membersQuery.data) {
      setSelected(new Set(membersQuery.data.map((s) => s.id)));
    }
  }, [membersQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () => replaceHostGroupMembers(hostGroupId, { server_ids: Array.from(selected) }),
    onSuccess: () => {
      toast.success("Membership updated");
      void queryClient.invalidateQueries({ queryKey: ["host-group-members", hostGroupId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/host-groups")}>
        <ArrowLeft className="h-4 w-4" />
        Back to host groups
      </Button>

      <QueryState isLoading={groupQuery.isLoading} isError={groupQuery.isError} error={groupQuery.error}>
        {groupQuery.data && (
          <>
            <PageHeader title={groupQuery.data.name} description={groupQuery.data.description ?? undefined} />

            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-sm">Members</CardTitle>
                  <CardDescription>
                    {selected.size} of {allServersQuery.data?.length ?? 0} servers selected — saving replaces the full
                    membership set.
                  </CardDescription>
                </div>
                <RoleGate minRole="operator">
                  <Button size="sm" disabled={saveMutation.isPending || selected.size === 0} onClick={() => saveMutation.mutate()}>
                    <Save className="h-4 w-4" />
                    {saveMutation.isPending ? "Saving…" : "Save membership"}
                  </Button>
                </RoleGate>
              </CardHeader>
              <CardContent>
                <QueryState
                  isLoading={allServersQuery.isLoading}
                  isError={allServersQuery.isError}
                  error={allServersQuery.error}
                  isEmpty={allServersQuery.data?.length === 0}
                  emptyMessage="No servers exist yet."
                >
                  <div className="max-h-[60vh] overflow-y-auto rounded-md border">
                    {allServersQuery.data?.map((server) => (
                      <label
                        key={server.id}
                        className="flex items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0 hover:bg-accent"
                      >
                        <Checkbox checked={selected.has(server.id)} onCheckedChange={() => toggle(server.id)} />
                        <span className="font-medium">{server.hostname}</span>
                        <span className="text-muted-foreground">{server.ip_address}</span>
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
