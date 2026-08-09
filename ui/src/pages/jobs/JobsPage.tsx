import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { RoleGate } from "@/layout/RoleGate";
import { listJobs, type JobStatus, type JobType } from "@/api/jobs";
import { formatDateTime } from "@/lib/format";
import { titleCase } from "@/lib/format";
import { TriggerJobDialog } from "./TriggerJobDialog";

const JOB_TYPES: JobType[] = [
  "bootstrap",
  "apply_updates",
  "gather_facts",
  "bulk_apply_updates",
  "run_command",
  "manage_package",
];
const JOB_STATUSES: JobStatus[] = ["pending", "running", "success", "failed"];

export function JobsPage() {
  const queryClient = useQueryClient();
  const [jobTypeFilter, setJobTypeFilter] = useState<JobType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [triggerOpen, setTriggerOpen] = useState(false);

  const jobsQuery = useQuery({
    queryKey: ["jobs", { jobTypeFilter, statusFilter }],
    queryFn: () =>
      listJobs({
        limit: 100,
        job_type: jobTypeFilter === "all" ? undefined : jobTypeFilter,
        status: statusFilter === "all" ? undefined : statusFilter,
      }),
  });

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Ansible-backed operations run against the fleet"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={triggerOpen} onOpenChange={setTriggerOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  Trigger job
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-lg">
                <TriggerJobDialog
                  onDone={() => {
                    setTriggerOpen(false);
                    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
                    toast.success("Job triggered");
                  }}
                />
              </DialogContent>
            </Dialog>
          </RoleGate>
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <Select value={jobTypeFilter} onValueChange={(v) => setJobTypeFilter(v as JobType | "all")}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Job type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All job types</SelectItem>
            {JOB_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {titleCase(t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as JobStatus | "all")}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {JOB_STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {titleCase(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <QueryState
        isLoading={jobsQuery.isLoading}
        isError={jobsQuery.isError}
        error={jobsQuery.error}
        isEmpty={jobsQuery.data?.length === 0}
        emptyMessage="No jobs match these filters."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Servers</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobsQuery.data?.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="font-medium">
                  <Link to={`/jobs/${job.id}`} className="hover:underline">
                    {titleCase(job.job_type)}
                  </Link>
                </TableCell>
                <TableCell>
                  <StatusBadge value={job.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">{titleCase(job.target_type)}</TableCell>
                <TableCell className="text-muted-foreground">{job.server_ids.length}</TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(job.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
