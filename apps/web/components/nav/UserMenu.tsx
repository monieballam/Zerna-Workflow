'use client';

import { useState } from 'react';
import { logoutAction } from '@/lib/actions';

interface UserMenuProps {
  email?: string;
}

const AUTH_DISABLED = ['1', 'true', 'yes', 'on'].includes(
  (process.env.NEXT_PUBLIC_AUTH_DISABLED ?? '').trim().toLowerCase()
);

export default function UserMenu({ email }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const initials = email ? email[0]?.toUpperCase() : 'U';

  if (AUTH_DISABLED) {
    return (
      <span
        className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary-600 text-white text-sm font-medium"
        title={email ?? 'Local user'}
        aria-label={email ? `Signed in as ${email}` : 'Local user'}
      >
        {initials}
      </span>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="User menu"
      >
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary-600 text-white text-sm font-medium">
          {initials}
        </span>
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="menu"
            className="absolute right-0 top-full mt-2 w-56 rounded-md border border-gray-200 bg-white shadow-lg z-50 py-1"
          >
            {email && (
              <div className="px-4 py-2 border-b border-gray-100">
                <p className="text-xs text-gray-500">Signed in as</p>
                <p className="text-sm font-medium text-gray-900 truncate">{email}</p>
              </div>
            )}
            <form action={logoutAction}>
              <button
                type="submit"
                role="menuitem"
                className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
              >
                Sign out
              </button>
            </form>
          </div>
        </>
      )}
    </div>
  );
}
