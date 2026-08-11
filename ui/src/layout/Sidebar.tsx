import type * as React from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Package,
  Layers,
  GitBranch,
  Server,
  ListChecks,
  ShieldCheck,
  Newspaper,
  Users,
  KeyRound,
  MapPin,
  ScrollText,
  TrendingUp,
  BookOpen,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getBranding, logoUrl } from "@/api/branding";
import { RoleGate } from "./RoleGate";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

// Monitor groups everything that's about observing fleet/job/compliance
// state over time rather than managing content or inventory — Dashboard,
// Jobs, Compliance, Trends, Audit Logs. Audit Logs stays admin-only (its
// own RoleGate below), the rest of this group is visible to every role,
// same as before the grouping.
const MONITOR_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck },
  { to: "/trends", label: "Trends", icon: TrendingUp },
];

const NAV_ITEMS: NavItem[] = [
  { to: "/repositories", label: "Repositories", icon: Package },
  { to: "/content-views", label: "Content Views", icon: Layers },
  { to: "/environments", label: "Lifecycle Environments", icon: GitBranch },
  { to: "/servers", label: "Servers", icon: Server },
  { to: "/errata", label: "Errata", icon: Newspaper },
  { to: "/host-groups", label: "Host Groups", icon: Users },
  { to: "/activation-keys", label: "Activation Keys", icon: KeyRound },
  { to: "/sites", label: "Sites", icon: MapPin },
  { to: "/documentation", label: "Documentation", icon: BookOpen },
  { to: "/settings", label: "Settings", icon: Settings },
];

// Fluent 2's left-rail active state (Teams/Outlook/Admin Center): a
// tinted background + colored icon/label + a left accent bar, not an
// inverted filled pill — the signature that distinguishes this from a
// generic admin-dashboard sidebar.
function navLinkClass(isActive: boolean): string {
  return cn(
    "relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-accent text-accent-foreground before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-primary"
      : "text-muted-foreground hover:bg-accent/60 hover:text-accent-foreground",
  );
}

export function Sidebar() {
  // Same-shape query as useApplyBranding (App.tsx) — TanStack Query
  // dedupes identical ["branding"] queries across components, so this
  // doesn't cause a second network fetch, just a second subscriber to
  // the same cached result.
  const brandingQuery = useQuery({ queryKey: ["branding"], queryFn: getBranding });

  return (
    <nav className="flex h-full w-60 shrink-0 flex-col border-r bg-secondary/50">
      <div className="flex h-14 items-center gap-2 border-b px-5">
        {brandingQuery.data?.has_logo ? (
          <img
            src={logoUrl(brandingQuery.data.updated_at)}
            alt="Groundctl"
            className="h-7 w-7 rounded-md object-contain"
          />
        ) : (
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-sm font-bold">
            G
          </div>
        )}
        <span className="text-sm font-semibold tracking-tight">Groundctl</span>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monitor</p>
        <ul className="mb-4 flex flex-col gap-0.5">
          {MONITOR_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => navLinkClass(isActive)}>
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
          <RoleGate minRole="admin">
            <li>
              <NavLink to="/audit-logs" className={({ isActive }) => navLinkClass(isActive)}>
                <ScrollText className="h-4 w-4 shrink-0" />
                <span className="truncate">Audit Logs</span>
              </NavLink>
            </li>
          </RoleGate>
        </ul>

        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => navLinkClass(isActive)}>
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
