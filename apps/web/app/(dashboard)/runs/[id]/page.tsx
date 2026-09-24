import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { createServerClient } from '@/lib/api';
import RunDetail from '@/components/runs/RunDetail';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  return { title: `Run ${id.slice(0, 8)}` };
}

export default async function RunDetailPage({ params }: PageProps) {
  const { id } = await params;
  const client = createServerClient();

  let run;
  try {
    run = await client.runs.get(id);
  } catch {
    notFound();
  }

  let artifacts: Awaited<ReturnType<typeof client.runs.listArtifacts>>['artifacts'] = [];
  try {
    const res = await client.runs.listArtifacts(id);
    artifacts = res.artifacts;
  } catch {
    // Non-fatal — show empty artifacts
  }

  return (
    <div>
      <div className="mb-6">
        <Link href="/runs" className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to runs
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">Run detail</h1>
      </div>

      <RunDetail initialRun={run} artifacts={artifacts} />
    </div>
  );
}
