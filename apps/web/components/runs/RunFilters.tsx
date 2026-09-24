'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useTransition } from 'react';
import type { RunStatus } from '@zerna/sdk';

const STATUSES: Array<{ value: RunStatus | ''; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'queued', label: 'Queued' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
];

export default function RunFilters() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();

  const updateParam = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      params.delete('page');
      startTransition(() => {
        router.push(`?${params.toString()}`);
      });
    },
    [router, searchParams]
  );

  return (
    <div className={`flex gap-3 flex-wrap ${isPending ? 'opacity-60' : ''}`}>
      <select
        value={searchParams.get('status') ?? ''}
        onChange={(e) => updateParam('status', e.target.value)}
        className="input"
        aria-label="Filter by status"
      >
        {STATUSES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>

      <input
        type="date"
        value={searchParams.get('from') ?? ''}
        onChange={(e) => updateParam('from', e.target.value)}
        className="input"
        aria-label="From date"
        title="From date"
      />
      <input
        type="date"
        value={searchParams.get('to') ?? ''}
        onChange={(e) => updateParam('to', e.target.value)}
        className="input"
        aria-label="To date"
        title="To date"
      />
    </div>
  );
}
