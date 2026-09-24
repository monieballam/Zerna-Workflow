'use client';

import { useState } from 'react';

interface Org {
  id: string;
  name: string;
}

interface OrgSelectorProps {
  orgs?: Org[];
  currentOrgId?: string;
}

export default function OrgSelector({ orgs = [], currentOrgId }: OrgSelectorProps) {
  const [open, setOpen] = useState(false);
  const current = orgs.find((o) => o.id === currentOrgId) ?? orgs[0];

  if (!current) {
    return <span className="text-sm text-gray-400 px-2">No organization</span>;
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-primary-100 text-primary-700 text-xs font-bold">
          {current.name[0]?.toUpperCase()}
        </span>
        <span>{current.name}</span>
        <svg
          className="h-4 w-4 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && orgs.length > 1 && (
        <ul
          role="listbox"
          className="absolute left-0 top-full mt-1 w-48 rounded-md border border-gray-200 bg-white shadow-lg z-50 py-1"
        >
          {orgs.map((org) => (
            <li
              key={org.id}
              role="option"
              aria-selected={org.id === current.id}
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer"
              onClick={() => setOpen(false)}
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-primary-100 text-primary-700 text-xs font-bold">
                {org.name[0]?.toUpperCase()}
              </span>
              {org.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
