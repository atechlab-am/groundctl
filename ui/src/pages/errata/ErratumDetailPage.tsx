import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getErratum, getAffectedServers } from "@/api/errata";
import { formatDateTime } from "@/lib/format";

export function ErratumDetailPage() {
  const { advisoryId } = useParams<{ advisoryId: string }>();
  const navigate = useNavigate();

  if (!advisoryId) return null;

  const erratumQuery = useQuery({ queryKey: ["erratum", advisoryId], queryFn: () => getErratum(advisoryId) });
  const affectedQuery = useQuery({
    queryKey: ["erratum-affected", advisoryId],
    queryFn: () => getAffectedServers(advisoryId),
  });

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/errata")}>
        <ArrowLeft className="h-4 w-4" />
        Back to errata
      </Button>

      <QueryState isLoading={erratumQuery.isLoading} isError={erratumQuery.isError} error={erratumQuery.error}>
        {erratumQuery.data && (
          <>
            <PageHeader title={erratumQuery.data.advisory_id} description={erratumQuery.data.title} />

            <div className="mb-6 flex flex-wrap gap-2">
              <Badge variant="outline" className="uppercase">
                {erratumQuery.data.source}
              </Badge>
              <Badge variant="outline">Published {formatDateTime(erratumQuery.data.published_at)}</Badge>
              {erratumQuery.data.severity && <Badge variant="warning">{erratumQuery.data.severity}</Badge>}
            </div>

            <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">CVEs</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {erratumQuery.data.cves.length === 0 ? (
                    <p className="text-sm text-muted-foreground">None listed.</p>
                  ) : (
                    erratumQuery.data.cves.map((cve) => (
                      <Badge key={cve} variant="outline">
                        {cve}
                      </Badge>
                    ))
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Fixed packages</CardTitle>
                </CardHeader>
                <CardContent>
                  {erratumQuery.data.packages.length === 0 ? (
                    <p className="text-sm text-muted-foreground">None listed.</p>
                  ) : (
                    <ul className="flex flex-col gap-1 text-sm">
                      {erratumQuery.data.packages.map((p, i) => (
                        <li key={i} className="flex justify-between">
                          <span>
                            {p.package_name} <span className="text-muted-foreground">({p.release})</span>
                          </span>
                          <span className="font-mono text-xs">{p.fixed_version}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Affected servers</CardTitle>
              </CardHeader>
              <CardContent>
                <QueryState
                  isLoading={affectedQuery.isLoading}
                  isError={affectedQuery.isError}
                  error={affectedQuery.error}
                  isEmpty={affectedQuery.data?.affected.length === 0}
                  emptyMessage="No servers currently affected (based on latest gathered facts)."
                >
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Hostname</TableHead>
                        <TableHead>Package</TableHead>
                        <TableHead>Installed</TableHead>
                        <TableHead>Fixed version</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {affectedQuery.data?.affected.map((a, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-medium">{a.hostname}</TableCell>
                          <TableCell>{a.package_name}</TableCell>
                          <TableCell className="font-mono text-xs">{a.installed_version}</TableCell>
                          <TableCell className="font-mono text-xs">{a.fixed_version}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </QueryState>
              </CardContent>
            </Card>
          </>
        )}
      </QueryState>
    </div>
  );
}
