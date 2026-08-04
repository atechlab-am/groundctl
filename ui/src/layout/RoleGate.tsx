import type { ReactNode } from "react";
import { useHasRole } from "@/auth/useHasRole";
import type { Role } from "@/api/auth";

/**
 * Renders children only if the current user's role is at least `minRole`.
 * Cosmetic convenience — hides nav items/buttons a role can't use so the
 * UI doesn't dangle affordances that would just 403. The server-side
 * require_role() dependency remains the real enforcement boundary.
 */
export function RoleGate({ minRole, children }: { minRole: Role; children: ReactNode }) {
  const allowed = useHasRole(minRole);
  if (!allowed) return null;
  return <>{children}</>;
}
