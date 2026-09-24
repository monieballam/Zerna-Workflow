import type { Metadata } from 'next';
import Link from 'next/link';
import { Suspense } from 'react';
import type { RunStatus } from '@zerna/sdk';
import { createServerClient } from '@/lib/api';
import RunTable from '@/components/runs/RunTable';
import RunFilters from '@/components/runs/RunFilters';
import Pagination from '@/components/datasets/Pagination';

export const metadata: Metadata = { title: 'Runs' };

interface PageProps {
  searchParams: Promise<{
    status?: string;
    from?: string;
    to?: string;
    page?: string;
  }>;
}

export default async function RunsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page ?? '1', 10));
  const status = params.status as RunStatus | undefined;

  const client = createServerClient();
  let runs = {
    items: [] as Awaited<ReturnType<typeof client.runs.list>>['items'],
    total: 0,
    total_pages: 1,
    page: 1,
    page_size: 20,
  };
  let datasets: Awaited<ReturnType<typeof client.datasets.list>>['items'] = [];

  try {
    const [runsRes, datasetsRes] = await Promise.allSettled([
      client.runs.list({ page, page_size: 20, status }),
      client.datasets.list({ page: 1, page_size: 200 }),
    ]);

    if (runsRes.status === 'fulfilled') {
      runs = runsRes.value;
    }
    if (datasetsRes.status === 'fulfilled') {
      datasets = datasetsRes.value.items;
    }
  } catch {
    // Render empty state if API unavailable
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Runs</h1>
        <Link href="/runs/new" className="btn-primary">
          New run
        </Link>
      </div>

      <div className="mb-4">
        <Suspense>
          <RunFilters />
        </Suspense>
      </div>

      <RunTable initialRuns={runs.items} datasets={datasets} />

      {runs.total_pages > 1 && (
        <div className="mt-4">
          <Pagination
            page={runs.page}
            totalPages={runs.total_pages}
            total={runs.total}
            pageSize={runs.page_size}
          />
        </div>
      )}
    </div>
  );
}
