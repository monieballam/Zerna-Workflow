'use client';

import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import type { OrganizationMember, UserRole } from '@zerna/sdk';

interface AdminMembersPanelProps {
  members: OrganizationMember[];
}

const ROLE_OPTIONS: UserRole[] = ['admin', 'member', 'viewer'];

export default function AdminMembersPanel({ members }: AdminMembersPanelProps) {
  const router = useRouter();
  const [roleDrafts, setRoleDrafts] = useState<Record<string, UserRole>>(
    Object.fromEntries(members.map((member) => [member.user_id, member.role]))
  );
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('member');
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const sortedMembers = useMemo(
    () => [...members].sort((left, right) => left.email.localeCompare(right.email)),
    [members]
  );

  async function saveRole(userId: string) {
    setPendingUserId(userId);
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(`/api/proxy/v1/admin/members/${userId}`, {
        method: 'PATCH',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({ role: roleDrafts[userId] }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Role update failed (${response.status})`);
      }
      setSuccess('Member role updated.');
      router.refresh();
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : 'Role update failed.');
    } finally {
      setPendingUserId(null);
    }
  }

  async function createMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch('/api/proxy/v1/admin/members', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password: password || undefined,
          role,
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Member creation failed (${response.status})`);
      }
      setSuccess('Member saved.');
      setEmail('');
      setPassword('');
      setRole('member');
      router.refresh();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Member creation failed.');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
          {success}
        </div>
      )}

      <form onSubmit={createMember} className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900">Create or attach user</h3>
        <p className="mt-1 text-sm text-gray-500">
          Leave password blank to attach an existing account. Add a password to create a brand-new
          account in this organization.
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-gray-700">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-gray-700">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-gray-700">Role</span>
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            >
              {ROLE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="submit"
            disabled={creating}
            className="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creating ? 'Saving…' : 'Save user'}
          </button>
        </div>
      </form>

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-200 px-5 py-4">
          <h3 className="text-sm font-semibold text-gray-900">Organization members</h3>
        </div>
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Email
              </th>
              <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Joined
              </th>
              <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Role
              </th>
              <th className="px-5 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {sortedMembers.map((member) => (
              <tr key={member.user_id}>
                <td className="px-5 py-4 text-sm text-gray-900">{member.email}</td>
                <td className="px-5 py-4 text-sm text-gray-500">
                  {new Date(member.joined_at).toLocaleDateString()}
                </td>
                <td className="px-5 py-4">
                  <select
                    value={roleDrafts[member.user_id] ?? member.role}
                    onChange={(event) =>
                      setRoleDrafts((current) => ({
                        ...current,
                        [member.user_id]: event.target.value as UserRole,
                      }))
                    }
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
                  >
                    {ROLE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-5 py-4 text-right">
                  <button
                    type="button"
                    onClick={() => void saveRole(member.user_id)}
                    disabled={pendingUserId === member.user_id}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {pendingUserId === member.user_id ? 'Saving…' : 'Update role'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
