import { useState } from "react";
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
  ChevronDown,
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

// Lifecycle groups content-view/environment management — the pieces of the
// promotion pipeline (define content, define the path it moves through).
const LIFECYCLE_ITEMS: NavItem[] = [
  { to: "/content-views", label: "Content Views", icon: Layers },
  { to: "/environments", label: "Lifecycle Environments", icon: GitBranch },
];

const NAV_ITEMS: NavItem[] = [
  { to: "/repositories", label: "Repositories", icon: Package },
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

interface NavSectionProps {
  label: string;
  items: NavItem[];
  defaultOpen?: boolean;
  children?: React.ReactNode;
}

// Collapsible sidebar group — header toggles a chevron + list visibility,
// state lives per-section (not persisted) so it just resets on reload,
// matching JobStatusIndicator's existing expand/collapse pattern elsewhere
// in the UI.
function NavSection({ label, items, defaultOpen = true, children }: NavSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <span>{label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open ? "" : "-rotate-90")} />
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-0.5">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => navLinkClass(isActive)}>
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
          {children}
        </ul>
      )}
    </div>
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
        <NavSection label="Monitor" items={MONITOR_ITEMS}>
          <RoleGate minRole="admin">
            <li>
              <NavLink to="/audit-logs" className={({ isActive }) => navLinkClass(isActive)}>
                <ScrollText className="h-4 w-4 shrink-0" />
                <span className="truncate">Audit Logs</span>
              </NavLink>
            </li>
          </RoleGate>
        </NavSection>

        <NavSection label="Lifecycle" items={LIFECYCLE_ITEMS} />

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
