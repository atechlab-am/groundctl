import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, ArrowUpCircle, RotateCcw, KeyRound } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
  listLifecycleEnvironments,
  createLifecycleEnvironment,
  promoteEnvironment,
  rollbackEnvironment,
  fetchEnvironmentGpgKey,
  type LifecycleEnvironmentCreate,
} from "@/api/environments";
import { errorMessage } from "@/lib/errors";

const EMPTY_FORM: LifecycleEnvironmentCreate = {
  name: "",
  path_name: "",
  position: 0,
  content_view_id: "",
  distro: "",
  release: "",
  publish_prefix: "",
  gpg_key_id: "",
  allow_unsigned: false,
};

export function EnvironmentsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<LifecycleEnvironmentCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<string | null>(null);
  const [rollbackVersionId, setRollbackVersionId] = useState("");

  const environmentsQuery = useQuery({
    queryKey: ["environments"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: LifecycleEnvironmentCreate) =>
      createLifecycleEnvironment({
        ...payload,
        gpg_key_id: payload.allow_unsigned ? payload.gpg_key_id || null : payload.gpg_key_id,
      }),
    onSuccess: () => {
      toast.success("Lifecycle environment created");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const promoteMutation = useMutation({
    mutationFn: (environmentId: string) => promoteEnvironment(environmentId, {}),
    onSuccess: () => {
      toast.success("Promoted to latest version");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const rollbackMutation = useMutation({
    mutationFn: ({ environmentId, versionId }: { environmentId: string; versionId: string }) =>
      rollbackEnvironment(environmentId, { content_view_version_id: versionId }),
    onSuccess: () => {
      toast.success("Rolled back");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setRollbackTarget(null);
      setRollbackVersionId("");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  async function handleViewGpgKey(environmentId: string) {
    try {
      const key = await fetchEnvironmentGpgKey(environmentId);
      const win = window.open("", "_blank");
      if (win) {
        win.document.title = "GPG public key";
        const pre = win.document.createElement("pre");
        pre.style.whiteSpace = "pre-wrap";
        pre.style.fontFamily = "monospace";
        pre.style.padding = "16px";
        pre.textContent = key;
        win.document.body.appendChild(pre);
      }
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!form.allow_unsigned && !form.gpg_key_id) {
      setFormError("gpg_key_id is required unless “Allow unsigned” is enabled");
      return;
    }
    createMutation.mutate(form);
  }

  return (
    <div>
      <PageHeader
        title="Lifecycle Environments"
        description="Publish prefixes clients point at — promote or roll back which content view version is live"
        actions={
          <RoleGate minRole="operator">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="h-4 w-4" />
                  New environment
                </Button>
              </DialogTrigger>
              <DialogContent>
                <form onSubmit={handleSubmit}>
                  <DialogHeader>
                    <DialogTitle>Create lifecycle environment</DialogTitle>
                    <DialogDescription>
                      Requires the content view's UUID (see Content Views for ids of views you've created).
                    </DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 grid grid-cols-2 gap-4">
                    {formError && <p className="col-span-2 text-sm text-destructive">{formError}</p>}
                    <Field label="Name" id="env-name">
                      <Input
                        id="env-name"
                        value={form.name}
                        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                        required
                      />
                    </Field>
                    <Field label="Path name" id="env-path">
                      <Input
                        id="env-path"
                        value={form.path_name}
                        onChange={(e) => setForm((f) => ({ ...f, path_name: e.target.value }))}
                        placeholder="default"
                        required
                      />
                    </Field>
                    <Field label="Position" id="env-position">
                      <Input
                        id="env-position"
                        type="number"
                        min={0}
                        value={form.position}
                        onChange={(e) => setForm((f) => ({ ...f, position: Number(e.target.value) }))}
                        required
                      />
                    </Field>
                    <Field label="Content view ID" id="env-cv">
                      <Input
                        id="env-cv"
                        value={form.content_view_id}
                        onChange={(e) => setForm((f) => ({ ...f, content_view_id: e.target.value }))}
                        placeholder="uuid"
                        required
                      />
                    </Field>
                    <Field label="Distro" id="env-distro">
                      <Input
                        id="env-distro"
                        value={form.distro}
                        onChange={(e) => setForm((f) => ({ ...f, distro: e.target.value }))}
                        placeholder="ubuntu"
                        required
                      />
                    </Field>
                    <Field label="Release" id="env-release">
                      <Input
                        id="env-release"
                        value={form.release}
                        onChange={(e) => setForm((f) => ({ ...f, release: e.target.value }))}
                        placeholder="jammy"
                        required
                      />
                    </Field>
                    <Field label="Publish prefix" id="env-prefix" full>
                      <Input
                        id="env-prefix"
                        value={form.publish_prefix}
                        onChange={(e) => setForm((f) => ({ ...f, publish_prefix: e.target.value }))}
                        placeholder="dev"
                        required
                      />
                    </Field>
                    <Field label="GPG key ID" id="env-gpg" full>
                      <Input
                        id="env-gpg"
                        value={form.gpg_key_id ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, gpg_key_id: e.target.value }))}
                        placeholder="uppercase hex fingerprint"
                        disabled={form.allow_unsigned}
                      />
                    </Field>
                    <div className="col-span-2 flex items-center gap-2">
                      <Checkbox
                        id="env-allow-unsigned"
                        checked={form.allow_unsigned}
                        onCheckedChange={(checked) => setForm((f) => ({ ...f, allow_unsigned: checked === true }))}
                      />
                      <Label htmlFor="env-allow-unsigned" className="font-normal">
                        Allow unsigned (not recommended) — required unless a GPG key ID is set
                      </Label>
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

      <QueryState
        isLoading={environmentsQuery.isLoading}
        isError={environmentsQuery.isError}
        error={environmentsQuery.error}
        isEmpty={environmentsQuery.data?.length === 0}
        emptyMessage="No lifecycle environments yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Path / position</TableHead>
              <TableHead>Publish prefix</TableHead>
              <TableHead>Current version</TableHead>
              <TableHead>Signing</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {environmentsQuery.data?.map((env) => (
              <TableRow key={env.id}>
                <TableCell className="font-medium">{env.name}</TableCell>
                <TableCell className="text-muted-foreground">
                  {env.path_name} #{env.position}
                </TableCell>
                <TableCell>{env.publish_prefix}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {env.current_version_id ? env.current_version_id.slice(0, 8) : "unpublished"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {env.gpg_key_id ? env.gpg_key_id.slice(0, 12) + "…" : "unsigned"}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    {env.gpg_key_id && (
                      <Button variant="outline" size="sm" onClick={() => void handleViewGpgKey(env.id)}>
                        <KeyRound className="h-3.5 w-3.5" />
                        Key
                      </Button>
                    )}
                    <RoleGate minRole="operator">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={promoteMutation.isPending && promoteMutation.variables === env.id}
                        onClick={() => promoteMutation.mutate(env.id)}
                      >
                        <ArrowUpCircle className="h-3.5 w-3.5" />
                        Promote
                      </Button>
                      <Dialog
                        open={rollbackTarget === env.id}
                        onOpenChange={(open) => setRollbackTarget(open ? env.id : null)}
                      >
                        <DialogTrigger asChild>
                          <Button variant="outline" size="sm">
                            <RotateCcw className="h-3.5 w-3.5" />
                            Rollback
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>Roll back {env.name}</DialogTitle>
                            <DialogDescription>
                              Only versions this environment has previously had live can be rolled back to; the
                              server enforces this and will reject anything else.
                            </DialogDescription>
                          </DialogHeader>
                          <div className="mt-4 flex flex-col gap-1.5">
                            <Label htmlFor="rollback-version">Content view version ID</Label>
                            <Input
                              id="rollback-version"
                              value={rollbackVersionId}
                              onChange={(e) => setRollbackVersionId(e.target.value)}
                              placeholder="uuid"
                            />
                          </div>
                          <DialogFooter className="mt-6">
                            <Button
                              disabled={rollbackMutation.isPending || !rollbackVersionId}
                              onClick={() =>
                                rollbackMutation.mutate({ environmentId: env.id, versionId: rollbackVersionId })
                              }
                            >
                              {rollbackMutation.isPending ? "Rolling back…" : "Roll back"}
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                    </RoleGate>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}

function Field({
  label,
  id,
  children,
  full,
}: {
  label: string;
  id: string;
  children: ReactNode;
  full?: boolean;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${full ? "col-span-2" : ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}
