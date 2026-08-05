import type * as React from "react";
import { NavLink } from "react-router-dom";
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
  BookOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { RoleGate } from "./RoleGate";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/repositories", label: "Repositories", icon: Package },
  { to: "/content-views", label: "Content Views", icon: Layers },
  { to: "/environments", label: "Lifecycle Environments", icon: GitBranch },
  { to: "/servers", label: "Servers", icon: Server },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck },
  { to: "/errata", label: "Errata", icon: Newspaper },
  { to: "/host-groups", label: "Host Groups", icon: Users },
  { to: "/activation-keys", label: "Activation Keys", icon: KeyRound },
  { to: "/sites", label: "Sites", icon: MapPin },
  { to: "/documentation", label: "Documentation", icon: BookOpen },
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
  return (
    <nav className="flex h-full w-60 shrink-0 flex-col border-r bg-secondary/50">
      <div className="flex h-14 items-center gap-2 border-b px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-sm font-bold">
          G
        </div>
        <span className="text-sm font-semibold tracking-tight">Groundctl</span>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
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
      </div>
    </nav>
  );
}
