'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useTransition } from 'react';

export default function DatasetFilters() {
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
      // Reset to page 1 when filters change
      params.delete('page');
      startTransition(() => {
        router.push(`?${params.toString()}`);
      });
    },
    [router, searchParams]
  );

  return (
    <div className={`flex gap-3 ${isPending ? 'opacity-60' : ''}`}>
      <input
        type="search"
        placeholder="Filter by name…"
        defaultValue={searchParams.get('name') ?? ''}
        onChange={(e) => updateParam('name', e.target.value)}
        className="input flex-1 max-w-xs"
        aria-label="Filter datasets by name"
      />
      <input
        type="text"
        placeholder="Filter by metadata key=value"
        defaultValue={searchParams.get('metadata') ?? ''}
        onChange={(e) => updateParam('metadata', e.target.value)}
        className="input flex-1 max-w-xs"
        aria-label="Filter datasets by metadata"
      />
    </div>
  );
}
