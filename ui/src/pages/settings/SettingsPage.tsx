import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useHasRole } from "@/auth/useHasRole";
import { MyAccountTab } from "./MyAccountTab";
import { UsersTab } from "./UsersTab";
import { AppearanceTab } from "./AppearanceTab";

export function SettingsPage() {
  const isAdmin = useHasRole("admin");

  return (
    <div>
      <PageHeader title="Settings" description="Your account, user management, and instance appearance" />
      <Tabs defaultValue="account">
        <TabsList>
          <TabsTrigger value="account">My Account</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
          {isAdmin && <TabsTrigger value="appearance">Appearance</TabsTrigger>}
        </TabsList>
        <TabsContent value="account">
          <MyAccountTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="users">
            <UsersTab />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="appearance">
            <AppearanceTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
