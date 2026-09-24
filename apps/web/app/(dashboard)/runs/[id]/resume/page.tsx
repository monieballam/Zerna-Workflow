import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { createServerClient } from '@/lib/api';
import RunCreateForm from '@/components/runs/RunCreateForm';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  return { title: `Resume ${id.slice(0, 8)}` };
}

export default async function ResumeRunPage({ params }: PageProps) {
  const { id } = await params;
  const client = createServerClient();

  let run;
  try {
    run = await client.runs.get(id);
  } catch {
    notFound();
  }

  if (run.status !== 'failed') {
    notFound();
  }

  if (run.dataset_deleted || !run.dataset_version_id) {
    return (
      <div>
        <div className="mb-6">
          <Link href={`/runs/${id}`} className="text-sm text-gray-500 hover:text-gray-700">
            ← Back to run
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">Resume unavailable</h1>
          <p className="mt-2 text-sm text-gray-600">
            This run cannot be resumed because its source dataset was deleted.
          </p>
        </div>
      </div>
    );
  }

  const [templatesRes, datasetsRes, runTemplateRes] = await Promise.allSettled([
    client.pipelines.list({ page: 1, page_size: 100 }),
    client.datasets.list({ page: 1, page_size: 100 }),
    client.pipelines.get(run.template_id),
  ]);

  let templates: import('@zerna/sdk').PipelineTemplate[] = [];
  if (templatesRes.status === 'fulfilled') {
    const raw = templatesRes.value;
    templates = Array.isArray(raw) ? raw : (raw.items ?? []);
  }
  if (runTemplateRes.status === 'fulfilled') {
    const runTemplate = runTemplateRes.value;
    if (!templates.some((t) => t.id === runTemplate.id)) {
      templates = [runTemplate, ...templates];
    }
  }
  const datasets = datasetsRes.status === 'fulfilled' ? datasetsRes.value.items : [];

  const initialParameters = Object.fromEntries(
    Object.entries(run.parameters ?? {}).filter(([key]) => key !== 'progress')
  );

  return (
    <div>
      <div className="mb-6">
        <Link href={`/runs/${id}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to run
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Resume failed run</h1>
        <p className="mt-1 text-sm text-gray-500">
          Correct the parameters that caused the failure, then continue from the failed step.
        </p>
        <p className="mt-2 text-xs text-amber-700">
          Change only settings relevant to the failed step or later. If you need to alter earlier
          preprocessing or clustering settings, start a fresh replay instead of resuming.
        </p>
      </div>

      <RunCreateForm
        templates={templates}
        datasets={datasets}
        mode="resume"
        submitLabel="Resume run"
        resumeRunId={run.id}
        initialTemplateId={run.template_id}
        initialDatasetVersionId={run.dataset_version_id ?? undefined}
        initialParameters={initialParameters}
        lockTemplateSelection
        lockDatasetSelection
      />
    </div>
  );
}
