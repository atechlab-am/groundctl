import type { ReactNode } from "react";
import { LogOut } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sidebar } from "./Sidebar";

const ROLE_BADGE_VARIANT: Record<string, "default" | "secondary" | "success"> = {
  admin: "default",
  operator: "secondary",
  viewer: "secondary",
};

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-end gap-3 border-b bg-card/80 px-6 backdrop-blur-sm">
          {user && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{user.username}</span>
                <Badge variant={ROLE_BADGE_VARIANT[user.role] ?? "secondary"} className="capitalize">
                  {user.role}
                </Badge>
              </div>
              <Button variant="ghost" size="sm" onClick={() => void logout()}>
                <LogOut className="h-4 w-4" />
                Log out
              </Button>
            </div>
          )}
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
