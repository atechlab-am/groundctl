import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, ArrowUpCircle, RotateCcw, KeyRound, Pencil, Layers, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
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
  listEnvironmentContentViews,
  assignContentViewToEnvironment,
  unassignContentViewFromEnvironment,
  promoteEnvironmentContentView,
  rollbackEnvironmentContentView,
  fetchEnvironmentContentViewGpgKey,
  type LifecycleEnvironmentCreate,
  type LifecycleEnvironmentRead,
  type EnvironmentContentViewRead,
} from "@/api/environments";
import { listContentViews, listContentViewVersions } from "@/api/contentViews";
import { errorMessage } from "@/lib/errors";

const EMPTY_FORM: LifecycleEnvironmentCreate = {
  name: "",
  description: "",
  prior_environment_id: "",
};

export function EnvironmentsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<LifecycleEnvironmentCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [editingEnv, setEditingEnv] = useState<LifecycleEnvironmentRead | null>(null);
  const [editDescription, setEditDescription] = useState("");
  const [contentViewsTarget, setContentViewsTarget] = useState<LifecycleEnvironmentRead | null>(null);

  const environmentsQuery = useQuery({
    queryKey: ["environments"],
    queryFn: () => listLifecycleEnvironments({ limit: 100 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: LifecycleEnvironmentCreate) =>
      createLifecycleEnvironment({
        ...payload,
        description: payload.description || null,
        prior_environment_id: payload.prior_environment_id || null,
      }),
    onSuccess: () => {
      toast.success("Lifecycle environment created — assign a content view to it to publish something");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () => updateLifecycleEnvironment(editingEnv!.id, { description: editDescription || null }),
    onSuccess: () => {
      toast.success("Environment updated");
      void queryClient.invalidateQueries({ queryKey: ["environments"] });
      setEditingEnv(null);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate(form);
  }

  function openEdit(env: LifecycleEnvironmentRead) {
    setEditingEnv(env);
    setEditDescription(env.description ?? "");
  }

  return (
    <div>
      <PageHeader
        title="Lifecycle Environments"
        description="Promotion paths (Library → QA → Dev → Prod) — assign any number of content views to each, independently"
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
                      Just name, description, and prior — this is pure path structure, with no content view of its
                      own. Assign content views afterward from the environment's "Content views" action.
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
                      <Label>Prior</Label>
                      {environmentsQuery.data?.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          No environments yet — this will start a new path.
                        </p>
                      ) : (
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
                            {environmentsQuery.data?.map((env) => (
                              <SelectItem key={env.id} value={env.id}>
                                {env.name} ({env.path_name} #{env.position})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
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
              <TableHead>Description</TableHead>
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
                <TableCell className="text-muted-foreground">{env.description ?? "—"}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => setContentViewsTarget(env)}>
                      <Layers className="h-3.5 w-3.5" />
                      Content views
                    </Button>
                    <RoleGate minRole="operator">
                      <Button variant="outline" size="sm" onClick={() => openEdit(env)}>
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </Button>
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
              <DialogDescription>Description only — name/path/position are fixed once created.</DialogDescription>
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

      <Dialog open={contentViewsTarget !== null} onOpenChange={(open) => !open && setContentViewsTarget(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{contentViewsTarget?.name} — content views</DialogTitle>
            <DialogDescription>
              Any number of content views can be assigned here, each independently promoted/rolled back.
            </DialogDescription>
          </DialogHeader>
          {contentViewsTarget && <EnvironmentContentViewsPanel environment={contentViewsTarget} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EnvironmentContentViewsPanel({ environment }: { environment: LifecycleEnvironmentRead }) {
  const queryClient = useQueryClient();
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignContentViewId, setAssignContentViewId] = useState("");
  const [assignVersionId, setAssignVersionId] = useState("");
  const [assignGpgKeyId, setAssignGpgKeyId] = useState("");
  const [assignAllowUnsigned, setAssignAllowUnsigned] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<EnvironmentContentViewRead | null>(null);
  const [rollbackVersionId, setRollbackVersionId] = useState("");

  const ecvsQuery = useQuery({
    queryKey: ["environment-content-views", environment.id],
    queryFn: () => listEnvironmentContentViews(environment.id),
  });

  const contentViewsQuery = useQuery({
    queryKey: ["content-views"],
    queryFn: () => listContentViews({ limit: 100 }),
  });

  const assignedIds = new Set(ecvsQuery.data?.map((ecv) => ecv.content_view_id));
  const assignableContentViews = contentViewsQuery.data?.filter((cv) => !assignedIds.has(cv.id)) ?? [];

  const versionsQuery = useQuery({
    queryKey: ["content-view-versions", assignContentViewId],
    queryFn: () => listContentViewVersions(assignContentViewId, { limit: 100 }),
    enabled: assignContentViewId !== "",
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["environment-content-views", environment.id] });
  };

  const assignMutation = useMutation({
    mutationFn: () =>
      assignContentViewToEnvironment(environment.id, {
        content_view_id: assignContentViewId,
        content_view_version_id: assignVersionId,
        gpg_key_id: assignGpgKeyId || null,
        allow_unsigned: assignAllowUnsigned,
      }),
    onSuccess: () => {
      toast.success("Content view assigned and published");
      invalidate();
      setAssignOpen(false);
      setAssignContentViewId("");
      setAssignVersionId("");
      setAssignGpgKeyId("");
      setAssignAllowUnsigned(false);
      setAssignError(null);
    },
    onError: (err) => setAssignError(errorMessage(err)),
  });

  const unassignMutation = useMutation({
    mutationFn: (contentViewId: string) => unassignContentViewFromEnvironment(environment.id, contentViewId),
    onSuccess: () => {
      toast.success("Content view unassigned");
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const promoteMutation = useMutation({
    mutationFn: (contentViewId: string) => promoteEnvironmentContentView(environment.id, contentViewId, {}),
    onSuccess: () => {
      toast.success("Promoted to latest version");
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const rollbackMutation = useMutation({
    mutationFn: ({ contentViewId, versionId }: { contentViewId: string; versionId: string }) =>
      rollbackEnvironmentContentView(environment.id, contentViewId, { content_view_version_id: versionId }),
    onSuccess: () => {
      toast.success("Rolled back");
      invalidate();
      setRollbackTarget(null);
      setRollbackVersionId("");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  async function handleViewGpgKey(contentViewId: string) {
    try {
      const key = await fetchEnvironmentContentViewGpgKey(environment.id, contentViewId);
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

  function handleAssignSubmit(e: FormEvent) {
    e.preventDefault();
    if (!assignContentViewId || !assignVersionId) {
      setAssignError("content view and version are both required");
      return;
    }
    if (!assignGpgKeyId && !assignAllowUnsigned) {
      setAssignError('gpg_key_id is required unless "Allow unsigned" is enabled');
      return;
    }
    setAssignError(null);
    assignMutation.mutate();
  }

  function contentViewName(contentViewId: string): string {
    return contentViewsQuery.data?.find((cv) => cv.id === contentViewId)?.name ?? contentViewId.slice(0, 8);
  }

  return (
    <div className="flex flex-col gap-4">
      <QueryState
        isLoading={ecvsQuery.isLoading}
        isError={ecvsQuery.isError}
        error={ecvsQuery.error}
        isEmpty={ecvsQuery.data?.length === 0}
        emptyMessage="No content views assigned yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Content view</TableHead>
              <TableHead>Publish prefix</TableHead>
              <TableHead>Current version</TableHead>
              <TableHead>Signing</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ecvsQuery.data?.map((ecv) => (
              <TableRow key={ecv.id}>
                <TableCell className="font-medium">{contentViewName(ecv.content_view_id)}</TableCell>
                <TableCell>{ecv.publish_prefix ?? "—"}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {ecv.current_version_id ? ecv.current_version_id.slice(0, 8) : "unpublished"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {ecv.gpg_key_id ? ecv.gpg_key_id.slice(0, 12) + "…" : "unsigned"}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    {ecv.gpg_key_id && (
                      <Button variant="outline" size="sm" onClick={() => void handleViewGpgKey(ecv.content_view_id)}>
                        <KeyRound className="h-3.5 w-3.5" />
                        Key
                      </Button>
                    )}
                    <RoleGate minRole="operator">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={promoteMutation.isPending && promoteMutation.variables === ecv.content_view_id}
                        onClick={() => promoteMutation.mutate(ecv.content_view_id)}
                      >
                        <ArrowUpCircle className="h-3.5 w-3.5" />
                        Promote
                      </Button>
                      <Dialog
                        open={rollbackTarget?.id === ecv.id}
                        onOpenChange={(open) => setRollbackTarget(open ? ecv : null)}
                      >
                        <DialogTrigger asChild>
                          <Button variant="outline" size="sm">
                            <RotateCcw className="h-3.5 w-3.5" />
                            Rollback
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>Roll back {contentViewName(ecv.content_view_id)}</DialogTitle>
                            <DialogDescription>
                              Only versions this assignment has previously had live can be rolled back to; the
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
                                rollbackMutation.mutate({
                                  contentViewId: ecv.content_view_id,
                                  versionId: rollbackVersionId,
                                })
                              }
                            >
                              {rollbackMutation.isPending ? "Rolling back…" : "Roll back"}
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={unassignMutation.isPending && unassignMutation.variables === ecv.content_view_id}
                        onClick={() => unassignMutation.mutate(ecv.content_view_id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Unassign
                      </Button>
                    </RoleGate>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>

      <RoleGate minRole="operator">
        <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline" className="self-start">
              <Plus className="h-3.5 w-3.5" />
              Assign content view
            </Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={handleAssignSubmit}>
              <DialogHeader>
                <DialogTitle>Assign a content view to {environment.name}</DialogTitle>
                <DialogDescription>
                  Publishes the chosen version immediately — this is the assignment's first promote.
                </DialogDescription>
              </DialogHeader>
              <div className="mt-4 flex flex-col gap-4">
                {assignError && <p className="text-sm text-destructive">{assignError}</p>}
                <div className="flex flex-col gap-1.5">
                  <Label>Content view</Label>
                  <Select
                    value={assignContentViewId || "__none__"}
                    onValueChange={(v) => {
                      setAssignContentViewId(v === "__none__" ? "" : v);
                      setAssignVersionId("");
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select a content view" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__" disabled>
                        Select a content view
                      </SelectItem>
                      {assignableContentViews.map((cv) => (
                        <SelectItem key={cv.id} value={cv.id}>
                          {cv.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Version</Label>
                  {!assignContentViewId ? (
                    <p className="text-sm text-muted-foreground">Pick a content view first.</p>
                  ) : (
                    <Select value={assignVersionId || "__none__"} onValueChange={(v) => setAssignVersionId(v === "__none__" ? "" : v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a version" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" disabled>
                          Select a version
                        </SelectItem>
                        {versionsQuery.data?.map((v) => (
                          <SelectItem key={v.id} value={v.id}>
                            v{v.version}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="assign-gpg">GPG key ID (optional)</Label>
                  <Input
                    id="assign-gpg"
                    value={assignGpgKeyId}
                    onChange={(e) => setAssignGpgKeyId(e.target.value)}
                    placeholder="uppercase hex fingerprint"
                  />
                </div>
                {!assignGpgKeyId && (
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="assign-allow-unsigned"
                      checked={assignAllowUnsigned}
                      onCheckedChange={(checked) => setAssignAllowUnsigned(checked === true)}
                    />
                    <Label htmlFor="assign-allow-unsigned" className="cursor-pointer font-normal">
                      Allow unsigned (not recommended)
                    </Label>
                  </div>
                )}
              </div>
              <DialogFooter className="mt-6">
                <Button type="submit" disabled={assignMutation.isPending}>
                  {assignMutation.isPending ? "Assigning…" : "Assign and publish"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </RoleGate>
    </div>
  );
}
