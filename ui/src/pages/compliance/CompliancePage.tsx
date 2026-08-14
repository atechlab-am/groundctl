import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { searchPackages, checkServerCompliance, type VersionComparator } from "@/api/compliance";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

const COMPARATORS: { value: VersionComparator; label: string }[] = [
  { value: "lt", label: "< less than" },
  { value: "le", label: "<= less than or equal" },
  { value: "eq", label: "= equal" },
  { value: "ge", label: ">= greater than or equal" },
  { value: "gt", label: "> greater than" },
];

export function CompliancePage() {
  const [packageName, setPackageName] = useState("");
  const [operator, setOperator] = useState<VersionComparator | "none">("none");
  const [compareVersion, setCompareVersion] = useState("");
  const [searchError, setSearchError] = useState<string | null>(null);

  const [checkServerId, setCheckServerId] = useState("");
  const [checkError, setCheckError] = useState<string | null>(null);

  const searchMutation = useMutation({
    mutationFn: () =>
      searchPackages({
        package_name: packageName,
        operator: operator === "none" ? undefined : operator,
        compare_version: operator === "none" ? undefined : compareVersion || undefined,
      }),
    onError: (err) => setSearchError(errorMessage(err)),
  });

  const checkMutation = useMutation({
    mutationFn: () => checkServerCompliance(checkServerId),
    onError: (err) => setCheckError(errorMessage(err)),
  });

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    setSearchError(null);
    searchMutation.mutate();
  }

  function handleCheck(e: FormEvent) {
    e.preventDefault();
    setCheckError(null);
    checkMutation.mutate();
  }

  return (
    <div>
      <PageHeader title="Compliance" description="Package drift search and per-server drift checks" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Package search</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSearch} className="flex flex-col gap-4">
              {searchError && <p className="text-sm text-destructive">{searchError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pkg-name">Package name</Label>
                <Input id="pkg-name" value={packageName} onChange={(e) => setPackageName(e.target.value)} required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>Comparator (optional)</Label>
                  <Select value={operator} onValueChange={(v) => setOperator(v as VersionComparator | "none")}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      {COMPARATORS.map((c) => (
                        <SelectItem key={c.value} value={c.value}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="pkg-version">Compare version</Label>
                  <Input
                    id="pkg-version"
                    value={compareVersion}
                    onChange={(e) => setCompareVersion(e.target.value)}
                    disabled={operator === "none"}
                  />
                </div>
              </div>
              <Button type="submit" disabled={searchMutation.isPending}>
                <Search className="h-4 w-4" />
                Search
              </Button>
            </form>

            {searchMutation.data && (
              <div className="mt-4">
                {searchMutation.data.matches.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No matches.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Hostname</TableHead>
                        <TableHead>Installed version</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {searchMutation.data.matches.map((m) => (
                        <TableRow key={m.server_id}>
                          <TableCell className="font-medium">{m.hostname}</TableCell>
                          <TableCell className="font-mono text-xs">{m.installed_version}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Quick drift check</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCheck} className="flex flex-col gap-4">
              {checkError && <p className="text-sm text-destructive">{checkError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="check-server">Server ID</Label>
                <Input id="check-server" value={checkServerId} onChange={(e) => setCheckServerId(e.target.value)} required />
              </div>
              <Button type="submit" disabled={checkMutation.isPending}>
                <ShieldCheck className="h-4 w-4" />
                Check compliance
              </Button>
            </form>

            {checkMutation.data && (
              <div className="mt-4">
                <p className="mb-2 text-xs text-muted-foreground">Checked {formatDateTime(checkMutation.data.checked_at)}</p>
                {checkMutation.data.drift.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No installed-package facts to compare.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Package</TableHead>
                        <TableHead>Installed</TableHead>
                        <TableHead>Available</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {checkMutation.data.drift.map((d) => (
                        <TableRow key={d.name}>
                          <TableCell className="font-medium">{d.name}</TableCell>
                          <TableCell className="font-mono text-xs">{d.installed_version ?? "—"}</TableCell>
                          <TableCell className="font-mono text-xs">{d.available_version ?? "—"}</TableCell>
                          <TableCell>
                            <StatusBadge value={d.status} />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
