import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Ban, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { QueryState } from "@/components/QueryState";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useAuth } from "@/auth/AuthContext";
import { registerUser, type Role, type UserCreate } from "@/api/auth";
import { listUsers, updateUser, deactivateUser, reactivateUser } from "@/api/users";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

const ROLE_BADGE_VARIANT: Record<Role, "default" | "secondary"> = {
  admin: "default",
  operator: "secondary",
  viewer: "secondary",
};

const EMPTY_FORM: UserCreate = { username: "", email: "", password: "", role: "viewer" };

export function UsersTab() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<UserCreate>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const usersQuery = useQuery({ queryKey: ["users"], queryFn: () => listUsers({ limit: 100 }) });

  const createMutation = useMutation({
    mutationFn: registerUser,
    onSuccess: () => {
      toast.success("User created");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => updateUser(userId, { role }),
    onSuccess: () => {
      toast.success("Role updated");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      toast.success("User deactivated");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const reactivateMutation = useMutation({
    mutationFn: reactivateUser,
    onSuccess: () => {
      toast.success("User reactivated");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate(form);
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Manage who can access groundctl. Deactivating a user revokes access immediately without deleting their
          history.
        </p>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="h-4 w-4" />
              New user
            </Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={handleSubmit}>
              <DialogHeader>
                <DialogTitle>Create user</DialogTitle>
                <DialogDescription>The user can sign in immediately with this password.</DialogDescription>
              </DialogHeader>
              <div className="mt-4 flex flex-col gap-4">
                {formError && <p className="text-sm text-destructive">{formError}</p>}
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-user-username">Username</Label>
                  <Input
                    id="new-user-username"
                    value={form.username}
                    onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-user-email">Email</Label>
                  <Input
                    id="new-user-email"
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-user-password">Password</Label>
                  <Input
                    id="new-user-password"
                    type="password"
                    autoComplete="new-password"
                    value={form.password}
                    onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                    required
                    minLength={8}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-user-role">Role</Label>
                  <Select value={form.role} onValueChange={(v) => setForm((f) => ({ ...f, role: v as Role }))}>
                    <SelectTrigger id="new-user-role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="viewer">Viewer</SelectItem>
                      <SelectItem value="operator">Operator</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
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
      </div>

      <QueryState
        isLoading={usersQuery.isLoading}
        isError={usersQuery.isError}
        error={usersQuery.error}
        isEmpty={usersQuery.data?.length === 0}
        emptyMessage="No users yet."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Username</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {usersQuery.data?.map((u) => {
              const isSelf = u.id === currentUser?.id;
              return (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">
                    {u.username}
                    {isSelf && <span className="ml-2 text-xs text-muted-foreground">(you)</span>}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{u.email}</TableCell>
                  <TableCell>
                    <Select
                      value={u.role}
                      onValueChange={(v) => roleMutation.mutate({ userId: u.id, role: v as Role })}
                      disabled={roleMutation.isPending && roleMutation.variables?.userId === u.id}
                    >
                      <SelectTrigger className="h-8 w-28">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="viewer">Viewer</SelectItem>
                        <SelectItem value="operator">Operator</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.active ? ROLE_BADGE_VARIANT[u.role] : "destructive"}>
                      {u.active ? "Active" : "Deactivated"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDateTime(u.created_at)}</TableCell>
                  <TableCell className="text-right">
                    {u.active ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={isSelf || (deactivateMutation.isPending && deactivateMutation.variables === u.id)}
                        onClick={() => deactivateMutation.mutate(u.id)}
                        title={isSelf ? "You can't deactivate your own account" : undefined}
                      >
                        <Ban className="h-3.5 w-3.5" />
                        Deactivate
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={reactivateMutation.isPending && reactivateMutation.variables === u.id}
                        onClick={() => reactivateMutation.mutate(u.id)}
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Reactivate
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
