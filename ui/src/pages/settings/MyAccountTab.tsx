import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/auth/AuthContext";
import { changeOwnPassword } from "@/api/auth";
import { errorMessage } from "@/lib/errors";

export function MyAccountTab() {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const changePasswordMutation = useMutation({
    mutationFn: changeOwnPassword,
    onSuccess: () => {
      toast.success("Password updated");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setFormError(null);
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (newPassword !== confirmPassword) {
      setFormError("New password and confirmation don't match");
      return;
    }
    if (newPassword.length < 8) {
      setFormError("New password must be at least 8 characters");
      return;
    }
    changePasswordMutation.mutate({ current_password: currentPassword, new_password: newPassword });
  }

  if (!user) return null;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Identity</CardTitle>
          <CardDescription>Your account details — contact an admin to change these.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Username</span>
            <span className="font-medium">{user.username}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Email</span>
            <span className="font-medium">{user.email}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Role</span>
            <Badge variant="secondary" className="capitalize">
              {user.role}
            </Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Change password</CardTitle>
          <CardDescription>Requires your current password.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex max-w-sm flex-col gap-4">
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="current-password">Current password</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirm-password">Confirm new password</Label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
            <Button type="submit" disabled={changePasswordMutation.isPending} className="mt-2 self-start">
              {changePasswordMutation.isPending ? "Updating…" : "Update password"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
