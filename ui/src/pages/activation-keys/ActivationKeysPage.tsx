import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Ban, Copy } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
  listActivationKeys,
  createActivationKey,
  revokeActivationKey,
  enrollmentScriptCommand,
  type ActivationKeyCreate,
  type ActivationKeyCreateResponse,
} from "@/api/activationKeys";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

const EMPTY_FORM: ActivationKeyCreate = {
  name: "",
  environment_id: "",
  host_group_id: "",
  tags: [],
  expires_at: "",
  max_uses: null,
};

export function ActivationKeysPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<ActivationKeyCreate>(EMPTY_FORM);
  const [tagsInput, setTagsInput] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<ActivationKeyCreateResponse | null>(null);

  const keysQuery = useQuery({ queryKey: ["activation-keys"], queryFn: () => listActivationKeys({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: (payload: ActivationKeyCreate) =>
      createActivationKey({
        ...payload,
        host_group_id: payload.host_group_id || null,
        expires_at: payload.expires_at ? new Date(payload.expires_at).toISOString() : null,
        tags: tagsInput
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    onSuccess: (key) => {
      void queryClient.invalidateQueries({ queryKey: ["activation-keys"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setTagsInput("");
      setFormError(null);
      setCreatedKey(key);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeActivationKey(id),
    onSuccess: () => {
      toast.success("Activation key revoked");
      void queryClient.invalidateQueries({ queryKey: ["activation-keys"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate(form);
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Could not copy — select and copy manually");
    }
  }

  return (
    <div>
      <PageHeader
        title="Activation Keys"
        description="Tokens for self-enrolling hosts into an environment"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New activation key
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create activation key</DialogTitle>
                    <DialogDescription>The raw token is shown once, immediately after creation.</DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="ak-name">Name</Label>
                      <Input id="ak-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="ak-env">Environment ID</Label>
                      <Input
                        id="ak-env"
                        value={form.environment_id}
                        onChange={(e) => setForm((f) => ({ ...f, environment_id: e.target.value }))}
                        placeholder="uuid"
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="ak-hostgroup">Host group ID (optional)</Label>
                      <Input
                        id="ak-hostgroup"
                        value={form.host_group_id ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, host_group_id: e.target.value }))}
                        placeholder="uuid"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="ak-tags">Tags (comma-separated)</Label>
                      <Input id="ak-tags" value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="ak-expires">Expires at (optional)</Label>
                        <Input
                          id="ak-expires"
                          type="datetime-local"
                          value={form.expires_at ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, expires_at: e.target.value }))}
                        />
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="ak-max-uses">Max uses (optional)</Label>
                        <Input
                          id="ak-max-uses"
                          type="number"
                          min={1}
                          value={form.max_uses ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, max_uses: e.target.value ? Number(e.target.value) : null }))}
                        />
                      </div>
                    </div>
                  </div>
                  <DialogFooter className="mt-6">
                    <Button type="submit" disabled={createMutation.isPending}>
                      {createMutation.isPending ? "Creating…" : "Create"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </RoleGate>
        }
      />

      <Dialog open={createdKey !== null} onOpenChange={(open) => !open && setCreatedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Activation key created</DialogTitle>
            <DialogDescription>
              Save this token now — it will never be shown again. The server only stores a hash of it.
            </DialogDescription>
          </DialogHeader>
          {createdKey && (
            <div className="mt-4 flex flex-col gap-4">
              <Alert variant="warning">
                <AlertTitle>This is the only time you'll see this token</AlertTitle>
                <AlertDescription>Copy it now and store it securely.</AlertDescription>
              </Alert>
              <div className="flex items-center gap-2 rounded-md border bg-muted p-3">
                <code className="flex-1 break-all text-xs">{createdKey.token}</code>
                <Button variant="outline" size="icon" onClick={() => void copyToClipboard(createdKey.token)}>
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Run this on the new host</Label>
                <p className="text-xs text-muted-foreground">
                  Registers the host with groundctl and installs groundctl's SSH key — ready to bootstrap
                  immediately after.
                </p>
                <div className="flex items-center gap-2 rounded-md border bg-muted p-3">
                  <code className="flex-1 break-all text-xs">{enrollmentScriptCommand(createdKey.token)}</code>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => void copyToClipboard(enrollmentScriptCommand(createdKey.token))}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}
          <DialogFooter className="mt-4">
            <Button onClick={() => setCreatedKey(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <QueryState
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        isEmpty={keysQuery.data?.length === 0}
        emptyMessage="No activation keys yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Tags</TableHead>
              <TableHead>Uses</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keysQuery.data?.map((key) => (
              <TableRow key={key.id}>
                <TableCell className="font-medium">{key.name}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {key.tags.map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {key.use_count}
                  {key.max_uses ? ` / ${key.max_uses}` : ""}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(key.expires_at)}</TableCell>
                <TableCell>
                  <Badge variant={key.revoked ? "destructive" : "success"}>{key.revoked ? "Revoked" : "Active"}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  <RoleGate minRole="operator">
                    {!key.revoked && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={revokeMutation.isPending && revokeMutation.variables === key.id}
                        onClick={() => revokeMutation.mutate(key.id)}
                      >
                        <Ban className="h-3.5 w-3.5" />
                        Revoke
                      </Button>
                    )}
                  </RoleGate>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
