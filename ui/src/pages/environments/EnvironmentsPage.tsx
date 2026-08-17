import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, ArrowUpCircle, RotateCcw, KeyRound, Pencil } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
  updateLifecycleEnvironment,
  promoteEnvironment,
  rollbackEnvironment,
  fetchEnvironmentGpgKey,
  type LifecycleEnvironmentCreate,
  type LifecycleEnvironmentRead,
} from "@/api/environments";
import { listContentViews } from "@/api/contentViews";
import { errorMessage } from "@/lib/errors";

const EMPTY_FORM: LifecycleEnvironmentCreate = {
  name: "",
  description: "",
  content_view_id: "",
  prior_environment_id: "",
  gpg_key_id: "",
};

export function EnvironmentsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<LifecycleEnvironmentCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<string | null>(null);
  const [rollbackVersionId, setRollbackVersionId] = useState("");
  const [editingEnv, setEditingEnv] = useState<LifecycleEnvironmentRead | null>(null);
  const [editDescription, setEditDescription] = useState("");
  const [editGpgKeyId, setEditGpgKeyId] = useState("");
  const [firstPromoteTarget, setFirstPromoteTarget] = useState<LifecycleEnvironmentRead | null>(null);
  const [firstPromoteVersionId, setFirstPromoteVersionId] = useState("");
  const [firstPromoteAllowUnsigned, setFirstPromoteAllowUnsigned] = useState(false);
  const [firstPromoteError, setFirstPromoteError] = useState<string | null>(null);

  const environmentsQuery = useQuery({
    queryKey: ["environments"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });

  const contentViewsQuery = useQuery({
    queryKey: ["content-views"],
    queryFn: () => listContentViews({ limit: 100 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: LifecycleEnvironmentCreate) =>
      createLifecycleEnvironment({
        ...payload,
        description: payload.description || null,
        // content_view_id is only sent when NOT chaining off a prior — the
        // server inherits it from the prior environment otherwise, and
        // rejects a mismatched explicit value if both were sent.
        content_view_id: payload.prior_environment_id ? null : payload.content_view_id || null,
        prior_environment_id: payload.prior_environment_id || null,
        gpg_key_id: payload.gpg_key_id || null,
      }),
    onSuccess: () => {
      toast.success("Lifecycle environment created — promote something to it to finish setting it up");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateLifecycleEnvironment(editingEnv!.id, {
        description: editDescription || null,
        gpg_key_id: editGpgKeyId || null,
      }),
    onSuccess: () => {
      toast.success("Environment updated");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setEditingEnv(null);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const promoteMutation = useMutation({
    mutationFn: (environmentId: string) => promoteEnvironment(environmentId, {}),
    onSuccess: () => {
      toast.success("Promoted to latest version");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  // An environment with no release yet has never been promoted — content_view_id
  // is already fixed at creation now, but "promote latest" still doesn't
  // mean anything until a version is chosen for the FIRST time, so this
  // stays a separate flow (dialog, explicit version id) rather than the
  // one-click button already-promoted environments use.
  const firstPromoteMutation = useMutation({
    mutationFn: () =>
      promoteEnvironment(firstPromoteTarget!.id, {
        content_view_version_id: firstPromoteVersionId,
        allow_unsigned: firstPromoteAllowUnsigned,
      }),
    onSuccess: (result) => {
      toast.success(`Promoted — live at ${result.published_url}`);
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setFirstPromoteTarget(null);
      setFirstPromoteVersionId("");
      setFirstPromoteAllowUnsigned(false);
      setFirstPromoteError(null);
    },
    onError: (err) => setFirstPromoteError(errorMessage(err)),
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
    if (!form.content_view_id && !form.prior_environment_id) {
      setFormError("Pick a content view (or a prior environment to chain onto)");
      return;
    }
    setFormError(null);
    createMutation.mutate(form);
  }

  function openEdit(env: LifecycleEnvironmentRead) {
    setEditingEnv(env);
    setEditDescription(env.description ?? "");
    setEditGpgKeyId(env.gpg_key_id ?? "");
  }

  function openFirstPromote(env: LifecycleEnvironmentRead) {
    setFirstPromoteTarget(env);
    setFirstPromoteVersionId("");
    setFirstPromoteAllowUnsigned(false);
    setFirstPromoteError(null);
  }

  function handleFirstPromote(e: FormEvent) {
    e.preventDefault();
    if (!firstPromoteVersionId) {
      setFirstPromoteError("content view version ID is required");
      return;
    }
    if (!firstPromoteTarget!.gpg_key_id && !firstPromoteAllowUnsigned) {
      setFirstPromoteError('gpg_key_id is required unless "Allow unsigned" is enabled');
      return;
    }
    setFirstPromoteError(null);
    firstPromoteMutation.mutate();
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
                      Every content view already has its own auto-created "Library" root — pick the content view
                      this environment belongs to, then optionally chain it onto an existing environment in that
                      content view's path (defaults to Library). Release and publish prefix get decided the
                      first time you promote something to it.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="mt-4 flex flex-col gap-4">
                    {formError && <p className="text-sm text-destructive">{formError}</p>}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="env-name">Name</Label>
                      <Input
                        id="env-name"
                        value={form.name}
                        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="env-description">Description</Label>
                      <Textarea
                        id="env-description"
                        value={form.description ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                        placeholder="Optional"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>Content view</Label>
                      <Select
                        value={form.content_view_id || "__none__"}
                        onValueChange={(v) =>
                          setForm((f) => ({
                            ...f,
                            content_view_id: v === "__none__" ? "" : v,
                            prior_environment_id: "",
                          }))
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select a content view" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__" disabled>
                            Select a content view
                          </SelectItem>
                          {contentViewsQuery.data?.map((cv) => (
                            <SelectItem key={cv.id} value={cv.id}>
                              {cv.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>Prior</Label>
                      {!form.content_view_id ? (
                        <p className="text-sm text-muted-foreground">Pick a content view first.</p>
                      ) : (
                        (() => {
                          const priorCandidates =
                            environmentsQuery.data?.filter((env) => env.content_view_id === form.content_view_id) ??
                            [];
                          return (
                            <Select
                              value={form.prior_environment_id || "__none__"}
                              onValueChange={(v) =>
                                setForm((f) => ({ ...f, prior_environment_id: v === "__none__" ? "" : v }))
                              }
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="None — start a new path" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__none__">None — start a new path</SelectItem>
                                {priorCandidates.map((env) => (
                                  <SelectItem key={env.id} value={env.id}>
                                    {env.name} ({env.path_name} #{env.position})
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          );
                        })()
                      )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="env-gpg">GPG key ID (optional)</Label>
                      <Input
                        id="env-gpg"
                        value={form.gpg_key_id ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, gpg_key_id: e.target.value }))}
                        placeholder="uppercase hex fingerprint — can also be set later"
                      />
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
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    {env.name}
                    {env.is_library && (
                      <Badge variant="secondary" title="Auto-created root environment — every content view has one">
                        Library
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {env.path_name} #{env.position}
                </TableCell>
                <TableCell>{env.publish_prefix ?? "—"}</TableCell>
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
                      <Button variant="outline" size="sm" onClick={() => openEdit(env)}>
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </Button>
                      {env.release === null ? (
                        <Button variant="outline" size="sm" onClick={() => openFirstPromote(env)}>
                          <ArrowUpCircle className="h-3.5 w-3.5" />
                          Promote…
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={promoteMutation.isPending && promoteMutation.variables === env.id}
                          onClick={() => promoteMutation.mutate(env.id)}
                        >
                          <ArrowUpCircle className="h-3.5 w-3.5" />
                          Promote
                        </Button>
                      )}
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

      <Dialog open={editingEnv !== null} onOpenChange={(open) => !open && setEditingEnv(null)}>
        <DialogContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              updateMutation.mutate();
            }}
          >
            <DialogHeader>
              <DialogTitle>Edit {editingEnv?.name}</DialogTitle>
              <DialogDescription>
                Description and signing key only — everything else is locked in once set by a promote.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-env-description">Description</Label>
                <Textarea
                  id="edit-env-description"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-env-gpg">GPG key ID</Label>
                <Input
                  id="edit-env-gpg"
                  value={editGpgKeyId}
                  onChange={(e) => setEditGpgKeyId(e.target.value)}
                  placeholder="uppercase hex fingerprint"
                />
              </div>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setEditingEnv(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={firstPromoteTarget !== null} onOpenChange={(open) => !open && setFirstPromoteTarget(null)}>
        <DialogContent>
          <form onSubmit={handleFirstPromote}>
            <DialogHeader>
              <DialogTitle>Promote {firstPromoteTarget?.name}</DialogTitle>
              <DialogDescription>
                This environment has never been promoted — pick a content view version to publish. Must be a
                version of this environment's own content view; every later promote reuses the latest version of
                that same content view.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 flex flex-col gap-4">
              {firstPromoteError && <p className="text-sm text-destructive">{firstPromoteError}</p>}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="first-promote-version">Content view version ID</Label>
                <Input
                  id="first-promote-version"
                  value={firstPromoteVersionId}
                  onChange={(e) => setFirstPromoteVersionId(e.target.value)}
                  placeholder="uuid — see Content Views for ids of versions you've published"
                  required
                />
              </div>
              {!firstPromoteTarget?.gpg_key_id && (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="first-promote-allow-unsigned"
                    checked={firstPromoteAllowUnsigned}
                    onCheckedChange={(checked) => setFirstPromoteAllowUnsigned(checked === true)}
                  />
                  <Label htmlFor="first-promote-allow-unsigned" className="cursor-pointer font-normal">
                    Allow unsigned (not recommended) — this environment has no GPG key configured
                  </Label>
                </div>
              )}
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => setFirstPromoteTarget(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={firstPromoteMutation.isPending}>
                {firstPromoteMutation.isPending ? "Promoting…" : "Promote"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
