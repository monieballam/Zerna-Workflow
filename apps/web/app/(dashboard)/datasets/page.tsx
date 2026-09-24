import type { Metadata } from 'next';
import Link from 'next/link';
import { Suspense } from 'react';
import { createServerClient } from '@/lib/api';
import DatasetTable from '@/components/datasets/DatasetTable';
import DatasetFilters from '@/components/datasets/DatasetFilters';
import Pagination from '@/components/datasets/Pagination';

export const metadata: Metadata = {
  title: 'Datasets',
};

interface PageProps {
  searchParams: Promise<{
    page?: string;
    page_size?: string;
    name?: string;
    metadata?: string;
    sort_by?: string;
    sort_order?: string;
  }>;
}

export default async function DatasetsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page ?? '1', 10));
  const pageSize = Math.min(100, Math.max(1, parseInt(params.page_size ?? '20', 10)));
  const sortBy = params.sort_by ?? 'created_at';
  const sortOrder = params.sort_order === 'asc' ? 'asc' : 'desc';

  const client = createServerClient();
  let result = { items: [], total: 0, page: 1, page_size: pageSize, total_pages: 0 } as Awaited<
    ReturnType<typeof client.datasets.list>
  >;

  try {
    result = await client.datasets.list({
      page,
      page_size: pageSize,
      ...(params.name ? { name: params.name } : {}),
    });
  } catch {
    // Render empty state if API is unavailable
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Datasets</h1>
        <Link href="/datasets/upload" className="btn-primary">
          Upload Dataset
        </Link>
      </div>

      <div className="mb-4">
        <Suspense>
          <DatasetFilters />
        </Suspense>
      </div>

      <Suspense fallback={<div className="card p-12 text-center text-gray-400">Loading…</div>}>
        <DatasetTable datasets={result.items} sortBy={sortBy} sortOrder={sortOrder} />
      </Suspense>

      <Suspense>
        <Pagination
          page={result.page}
          totalPages={result.total_pages}
          total={result.total}
          pageSize={result.page_size}
        />
      </Suspense>
    </div>
  );
}
