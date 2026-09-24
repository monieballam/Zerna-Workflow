import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import RunExplorerWorkspace from '@/components/runs/RunExplorerWorkspace';
import { createServerClient } from '@/lib/api';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  return { title: `Run ${id.slice(0, 8)} Explorer` };
}

export default async function RunExplorerPage({ params }: PageProps) {
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
    // Non-fatal: keep the explorer workspace available even when artifacts fail to load.
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/runs/${id}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to run detail
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Completed Run Explorer</h1>
        <p className="mt-1 text-sm text-gray-500">
          Explore the completed run, inspect saved metrics and embeddings, and download the
          persisted outputs from one place.
        </p>
        {run.status !== 'completed' && (
          <p className="mt-2 text-sm text-amber-600">
            This run is not completed yet. Some explorer tabs may be unavailable until outputs are
            finalized.
          </p>
        )}
      </div>

      <RunExplorerWorkspace runId={id} artifacts={artifacts} />
    </div>
  );
}
