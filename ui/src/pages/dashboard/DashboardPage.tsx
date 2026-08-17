import type { ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Server, GitBranch, ListChecks, AlertTriangle } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { listServers } from "@/api/servers";
import { listLifecycleEnvironments } from "@/api/environments";
import { listJobs } from "@/api/jobs";
import { formatDateTime } from "@/lib/format";

// Composed entirely client-side from existing list endpoints — there is no
// dedicated dashboard/aggregation endpoint on the backend (out of scope per
// the build spec: "No new backend aggregation endpoint").
export function DashboardPage() {
  const serversQuery = useQuery({ queryKey: ["servers", "dashboard"], queryFn: () => listServers({ limit: 100 }) });
  const environmentsQuery = useQuery({
    queryKey: ["environments", "dashboard"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });
  const jobsQuery = useQuery({ queryKey: ["jobs", "dashboard"], queryFn: () => listJobs({ limit: 10 }) });

  const servers = serversQuery.data ?? [];
  const byStatus = {
    registered: servers.filter((s) => s.status === "registered").length,
    bootstrapped: servers.filter((s) => s.status === "bootstrapped").length,
    unreachable: servers.filter((s) => s.status === "unreachable").length,
  };

  return (
    <div>
      <PageHeader title="Dashboard" description="Fleet overview at a glance" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Server}
          label="Total servers"
          value={serversQuery.isLoading ? undefined : servers.length}
          sub={`${byStatus.bootstrapped} bootstrapped`}
        />
        <StatCard
          icon={AlertTriangle}
          label="Unreachable"
          value={serversQuery.isLoading ? undefined : byStatus.unreachable}
          sub="servers"
          tone={byStatus.unreachable > 0 ? "destructive" : undefined}
        />
        <StatCard
          icon={GitBranch}
          label="Lifecycle environments"
          value={environmentsQuery.isLoading ? undefined : environmentsQuery.data?.length}
          sub="configured"
        />
        <StatCard
          icon={ListChecks}
          label="Recent jobs"
          value={jobsQuery.isLoading ? undefined : jobsQuery.data?.length}
          sub="last 10"
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Lifecycle environments</CardTitle>
          </CardHeader>
          <CardContent>
            {environmentsQuery.isLoading ? (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : environmentsQuery.data && environmentsQuery.data.length > 0 ? (
              <ul className="flex flex-col divide-y">
                {environmentsQuery.data.map((env) => (
                  <li key={env.id} className="flex items-center justify-between py-2 text-sm">
                    <Link to="/environments" className="font-medium hover:underline">
                      {env.name}
                    </Link>
                    <span className="text-muted-foreground">
                      {env.path_name} #{env.position}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No lifecycle environments yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent jobs</CardTitle>
          </CardHeader>
          <CardContent>
            {jobsQuery.isLoading ? (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : jobsQuery.data && jobsQuery.data.length > 0 ? (
              <ul className="flex flex-col divide-y">
                {jobsQuery.data.map((job) => (
                  <li key={job.id} className="flex items-center justify-between py-2 text-sm">
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
            ) : (
              <p className="text-sm text-muted-foreground">No jobs yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: number | undefined;
  sub: string;
  tone?: "destructive";
}) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between p-5">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          {value === undefined ? (
            <Skeleton className="mt-1 h-8 w-12" />
          ) : (
            <p className={`mt-1 text-2xl font-semibold ${tone === "destructive" ? "text-destructive" : ""}`}>{value}</p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
        </div>
        <Icon className={`h-5 w-5 ${tone === "destructive" ? "text-destructive" : "text-muted-foreground"}`} />
      </CardContent>
    </Card>
  );
}
