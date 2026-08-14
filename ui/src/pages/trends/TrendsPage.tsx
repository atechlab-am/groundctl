import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StackedBarChart, type BarDatum } from "@/components/StackedBarChart";
import { getJobTrends, getComplianceTrends } from "@/api/trends";

const RANGE_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

export function TrendsPage() {
  const [days, setDays] = useState("14");
  const numDays = Number(days);

  const jobTrendsQuery = useQuery({
    queryKey: ["trends", "jobs", numDays],
    queryFn: () => getJobTrends(numDays),
  });
  const complianceTrendsQuery = useQuery({
    queryKey: ["trends", "compliance", numDays],
    queryFn: () => getComplianceTrends(numDays),
  });

  const jobData: BarDatum[] =
    jobTrendsQuery.data?.map((p) => ({
      label: shortDate(p.date),
      values: { success: p.success, failed: p.failed, running: p.running, pending: p.pending },
    })) ?? [];

  const complianceData: BarDatum[] =
    complianceTrendsQuery.data?.map((p) => ({
      label: shortDate(p.date),
      values: { outdated: p.outdated, up_to_date: p.up_to_date },
    })) ?? [];

  const jobTotals = jobTrendsQuery.data?.reduce(
    (acc, p) => ({ success: acc.success + p.success, failed: acc.failed + p.failed }),
    { success: 0, failed: 0 },
  );
  const totalChecks = complianceTrendsQuery.data?.reduce((sum, p) => sum + p.checks, 0) ?? 0;

  return (
    <div>
      <PageHeader
        title="Trends"
        description="Job outcomes and compliance drift over time"
        actions={
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Job outcomes</CardTitle>
            <CardDescription>
              {jobTotals ? `${jobTotals.success} succeeded, ${jobTotals.failed} failed` : "Daily job counts by status"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <QueryState
              isLoading={jobTrendsQuery.isLoading}
              isError={jobTrendsQuery.isError}
              error={jobTrendsQuery.error}
            >
              <StackedBarChart
                data={jobData}
                series={[
                  { key: "success", label: "Success", colorVar: "--success" },
                  { key: "failed", label: "Failed", colorVar: "--destructive" },
                  { key: "running", label: "Running", colorVar: "--warning" },
                  { key: "pending", label: "Pending", colorVar: "--muted-foreground" },
                ]}
                emptyMessage="No jobs ran in this range."
              />
            </QueryState>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Compliance drift</CardTitle>
            <CardDescription>
              {totalChecks > 0
                ? `${totalChecks} compliance check${totalChecks === 1 ? "" : "s"} run in this range`
                : "Outdated vs. up-to-date packages per compliance check"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <QueryState
              isLoading={complianceTrendsQuery.isLoading}
              isError={complianceTrendsQuery.isError}
              error={complianceTrendsQuery.error}
            >
              <StackedBarChart
                data={complianceData}
                series={[
                  { key: "outdated", label: "Outdated", colorVar: "--warning" },
                  { key: "up_to_date", label: "Up to date", colorVar: "--success" },
                ]}
                emptyMessage="No compliance checks ran in this range."
              />
            </QueryState>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
