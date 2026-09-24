'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

interface Props {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
}

export default function Pagination({ page, totalPages, total, pageSize }: Props) {
  const searchParams = useSearchParams();

  function pageHref(p: number): string {
    const params = new URLSearchParams(searchParams.toString());
    params.set('page', String(p));
    return `?${params.toString()}`;
  }

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-between mt-4">
      <p className="text-sm text-gray-500">
        Showing {start}–{end} of {total.toLocaleString()} datasets
      </p>
      <nav className="flex gap-1" aria-label="Pagination">
        <Link
          href={pageHref(page - 1)}
          aria-disabled={page <= 1}
          className={`px-3 py-1.5 text-sm rounded border ${
            page <= 1
              ? 'pointer-events-none text-gray-300 border-gray-200'
              : 'text-gray-700 border-gray-300 hover:bg-gray-50'
          }`}
        >
          Previous
        </Link>
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          const p = i + 1;
          return (
            <Link
              key={p}
              href={pageHref(p)}
              aria-current={p === page ? 'page' : undefined}
              className={`px-3 py-1.5 text-sm rounded border ${
                p === page
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'text-gray-700 border-gray-300 hover:bg-gray-50'
              }`}
            >
              {p}
            </Link>
          );
        })}
        <Link
          href={pageHref(page + 1)}
          aria-disabled={page >= totalPages}
          className={`px-3 py-1.5 text-sm rounded border ${
            page >= totalPages
              ? 'pointer-events-none text-gray-300 border-gray-200'
              : 'text-gray-700 border-gray-300 hover:bg-gray-50'
          }`}
        >
          Next
        </Link>
      </nav>
    </div>
  );
}
