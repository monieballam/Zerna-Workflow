import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound, redirect } from 'next/navigation';
import RunArtifactPreview from '@/components/runs/RunArtifactPreview';
import { createServerClient } from '@/lib/api';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface PageProps {
  params: Promise<{ id: string; artifactId: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  return { title: `Run ${id.slice(0, 8)} Artifact Preview` };
}

export default async function RunArtifactPreviewPage({ params }: PageProps) {
  const { id, artifactId } = await params;
  const client = createServerClient();

  try {
    await client.runs.get(id);
  } catch {
    notFound();
  }

  let artifacts: Awaited<ReturnType<typeof client.runs.listArtifacts>>['artifacts'] = [];
  try {
    const response = await client.runs.listArtifacts(id);
    artifacts = response.artifacts;
  } catch {
    notFound();
  }

  const artifact = artifacts.find((item) => item.id === artifactId);
  if (!artifact) notFound();

  if (artifact.artifact_type === 'h5ad') {
    redirect(`/runs/${id}/explore`);
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/runs/${id}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to run detail
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Artifact preview</h1>
        <p className="mt-1 text-sm text-gray-500">
          Preview saved run outputs in the app, then download the full artifact when you need the
          complete file externally.
        </p>
      </div>

      <div className="card p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-gray-900">
              {artifact.artifact_type === 'de_results'
                ? 'Differential expression'
                : artifact.artifact_type === 'pathway_scores'
                  ? 'Pathway scores'
                  : artifact.artifact_type === 'liana_results'
                    ? 'Ligand-receptor'
                    : artifact.artifact_type}
            </p>
            <p className="mt-1 text-sm text-gray-500">
              Stored artifact preview for run <span className="font-mono">{id}</span>.
            </p>
          </div>
          {artifact.download_url ? (
            <a
              href={
                artifact.download_url.startsWith('/api/proxy') ||
                !artifact.download_url.startsWith('/')
                  ? artifact.download_url
                  : `/api/proxy${artifact.download_url}`
              }
              download
              className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 transition-colors"
            >
              Download artifact
            </a>
          ) : null}
        </div>
      </div>

      <RunArtifactPreview runId={id} artifact={artifact} />
    </div>
  );
}
