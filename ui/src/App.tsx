import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { AppShell } from "@/layout/AppShell";
import { Toaster } from "@/components/ui/sonner";
import { LoginPage } from "@/pages/login/LoginPage";
import { DashboardPage } from "@/pages/dashboard/DashboardPage";
import { RepositoriesPage } from "@/pages/repositories/RepositoriesPage";
import { ContentViewsPage } from "@/pages/content-views/ContentViewsPage";
import { EnvironmentsPage } from "@/pages/environments/EnvironmentsPage";
import { ServersPage } from "@/pages/servers/ServersPage";
import { ServerDetailPage } from "@/pages/servers/ServerDetailPage";
import { JobsPage } from "@/pages/jobs/JobsPage";
import { JobDetailPage } from "@/pages/jobs/JobDetailPage";
import { CompliancePage } from "@/pages/compliance/CompliancePage";
import { ErrataPage } from "@/pages/errata/ErrataPage";
import { ErratumDetailPage } from "@/pages/errata/ErratumDetailPage";
import { HostGroupsPage } from "@/pages/host-groups/HostGroupsPage";
import { HostGroupDetailPage } from "@/pages/host-groups/HostGroupDetailPage";
import { ActivationKeysPage } from "@/pages/activation-keys/ActivationKeysPage";
import { SitesPage } from "@/pages/sites/SitesPage";
import { SiteDetailPage } from "@/pages/sites/SiteDetailPage";
import { AuditLogsPage } from "@/pages/audit-logs/AuditLogsPage";
import { DocumentationPage } from "@/pages/documentation/DocumentationPage";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { RoleGate } from "@/layout/RoleGate";
import { useApplyBranding } from "@/lib/useApplyBranding";

function Shell({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}

// Runs on every load, logged in or not (see useApplyBranding) — needs to
// be inside QueryClientProvider (uses useQuery) but doesn't need to be
// inside AuthProvider, since branding has no dependency on auth state.
function BrandingEffect() {
  useApplyBranding();
  return null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrandingEffect />
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<Shell><DashboardPage /></Shell>} />
            <Route path="/repositories" element={<Shell><RepositoriesPage /></Shell>} />
            <Route path="/content-views" element={<Shell><ContentViewsPage /></Shell>} />
            <Route path="/environments" element={<Shell><EnvironmentsPage /></Shell>} />
            <Route path="/servers" element={<Shell><ServersPage /></Shell>} />
            <Route path="/servers/:serverId" element={<Shell><ServerDetailPage /></Shell>} />
            <Route path="/jobs" element={<Shell><JobsPage /></Shell>} />
            <Route path="/jobs/:jobId" element={<Shell><JobDetailPage /></Shell>} />
            <Route path="/compliance" element={<Shell><CompliancePage /></Shell>} />
            <Route path="/errata" element={<Shell><ErrataPage /></Shell>} />
            <Route path="/errata/:advisoryId" element={<Shell><ErratumDetailPage /></Shell>} />
            <Route path="/host-groups" element={<Shell><HostGroupsPage /></Shell>} />
            <Route path="/host-groups/:hostGroupId" element={<Shell><HostGroupDetailPage /></Shell>} />
            <Route path="/activation-keys" element={<Shell><ActivationKeysPage /></Shell>} />
            <Route path="/sites" element={<Shell><SitesPage /></Shell>} />
            <Route path="/sites/:siteId" element={<Shell><SiteDetailPage /></Shell>} />
            <Route path="/documentation" element={<Shell><DocumentationPage /></Shell>} />
            <Route path="/documentation/:slug" element={<Shell><DocumentationPage /></Shell>} />
            <Route path="/settings" element={<Shell><SettingsPage /></Shell>} />
            <Route
              path="/audit-logs"
              element={
                <Shell>
                  <RoleGate minRole="admin">
                    <AuditLogsPage />
                  </RoleGate>
                </Shell>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      <Toaster />
    </QueryClientProvider>
  );
}
