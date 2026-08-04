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
];

export function Sidebar() {
  return (
    <nav className="flex h-full w-60 shrink-0 flex-col border-r bg-card">
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
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  )
                }
              >
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
          <RoleGate minRole="admin">
            <li>
              <NavLink
                to="/audit-logs"
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  )
                }
              >
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
