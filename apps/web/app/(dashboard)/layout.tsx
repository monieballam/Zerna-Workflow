import Navbar from '@/components/nav/Navbar';
import Sidebar from '@/components/nav/Sidebar';
import { requireAuthenticatedUser } from '@/lib/require-auth';

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const user = await requireAuthenticatedUser();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar
        email={user.email}
        orgs={user.organizations.map((organization) => ({
          id: organization.organization_id,
          name: organization.organization_name,
        }))}
        currentOrgId={user.active_organization_id ?? undefined}
      />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar isAdmin={user.active_role === 'admin'} />
        <main className="flex-1 overflow-y-auto p-6 bg-gray-50">{children}</main>
      </div>
    </div>
  );
}
