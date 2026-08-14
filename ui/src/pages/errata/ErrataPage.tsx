import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listErrata, type ErratumSource } from "@/api/errata";
import { formatDateTime } from "@/lib/format";

export function ErrataPage() {
  const [source, setSource] = useState<ErratumSource | "all">("all");
  const [cve, setCve] = useState("");
  const [publishedSince, setPublishedSince] = useState("");

  const erratumQuery = useQuery({
    queryKey: ["errata", { source, cve, publishedSince }],
    queryFn: () =>
      listErrata({
        limit: 100,
        source: source === "all" ? undefined : source,
        cve: cve || undefined,
        published_since: publishedSince ? new Date(publishedSince).toISOString() : undefined,
      }),
  });

  return (
    <div>
      <PageHeader title="Errata" description="Security advisories (USN/DSA) tracked against the fleet" />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label>Source</Label>
          <Select value={source} onValueChange={(v) => setSource(v as ErratumSource | "all")}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="usn">USN</SelectItem>
              <SelectItem value="dsa">DSA</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="errata-cve">CVE</Label>
          <Input id="errata-cve" value={cve} onChange={(e) => setCve(e.target.value)} placeholder="CVE-2026-..." className="w-48" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="errata-since">Published since</Label>
          <Input
            id="errata-since"
            type="date"
            value={publishedSince}
            onChange={(e) => setPublishedSince(e.target.value)}
            className="w-40"
          />
        </div>
      </div>

      <QueryState
        isLoading={erratumQuery.isLoading}
        isError={erratumQuery.isError}
        error={erratumQuery.error}
        isEmpty={erratumQuery.data?.length === 0}
        emptyMessage="No errata match these filters."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Advisory</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>CVEs</TableHead>
              <TableHead>Published</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {erratumQuery.data?.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="font-medium">
                  <Link to={`/errata/${encodeURIComponent(e.advisory_id)}`} className="hover:underline">
                    {e.advisory_id}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="uppercase">
                    {e.source}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-md truncate">{e.title}</TableCell>
                <TableCell className="text-muted-foreground">{e.cves.length}</TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(e.published_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
