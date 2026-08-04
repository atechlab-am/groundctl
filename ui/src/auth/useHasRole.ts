import { useAuth } from "./AuthContext";
import type { Role } from "@/api/auth";

// Hierarchical role ranking — mirrors app/auth.py's ROLE_RANK exactly.
// An admin passes an operator-or-viewer gate; an operator passes a viewer
// gate; a viewer only passes a viewer gate.
export const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  operator: 1,
  admin: 2,
};

/**
 * Returns true if the current user's role is at least `minRole`. Used to
 * hide (not just disable) nav items and action buttons a role can't use —
 * the server-side require_role() dependency remains the real enforcement
 * boundary; this is UI convenience only.
 */
export function useHasRole(minRole: Role): boolean {
  const { user } = useAuth();
  if (!user) return false;
  return ROLE_RANK[user.role] >= ROLE_RANK[minRole];
}
