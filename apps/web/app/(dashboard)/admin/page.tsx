import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import AdminFeedbackTable from '@/components/admin/AdminFeedbackTable';
import AdminMembersPanel from '@/components/admin/AdminMembersPanel';
import { createServerClient } from '@/lib/api';
import { requireAuthenticatedUser } from '@/lib/require-auth';

export const metadata: Metadata = { title: 'Admin' };

export default async function AdminPage() {
  const user = await requireAuthenticatedUser();
  if (user.active_role !== 'admin') {
    redirect('/dashboard');
  }

  const client = createServerClient();
  const [membersResult, feedbackResult] = await Promise.allSettled([
    client.admin.listMembers(),
    client.admin.listFeedback({ page: 1, page_size: 100 }),
  ]);

  const members = membersResult.status === 'fulfilled' ? membersResult.value.items : [];
  const feedback = feedbackResult.status === 'fulfilled' ? feedbackResult.value.items : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin</h1>
        <p className="mt-2 max-w-3xl text-sm text-gray-500">
          Review feedback with the exact dataset and run settings captured at submission time, and
          manage organization roles. The bootstrap account <strong>admin@zerna.local</strong> is
          promoted to admin automatically when present.
        </p>
      </div>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Members</h2>
          <p className="mt-1 text-sm text-gray-500">
            Promote members to admins, attach existing users, or create a new admin directly.
          </p>
        </div>
        <AdminMembersPanel members={members} />
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Feedback review</h2>
          <p className="mt-1 text-sm text-gray-500">
            All organization feedback with submitter, dataset/run context, and run parameters.
          </p>
        </div>
        <AdminFeedbackTable items={feedback} />
      </section>
    </div>
  );
}
