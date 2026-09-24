import type { Metadata } from 'next';
import Link from 'next/link';
import { createServerClient } from '@/lib/api';
import RunCreateForm from '@/components/runs/RunCreateForm';

export const metadata: Metadata = { title: 'New Run' };

export default async function NewRunPage() {
  const client = createServerClient();

  const [templatesRes, datasetsRes] = await Promise.allSettled([
    client.pipelines.list({ page: 1, page_size: 100 }),
    client.datasets.list({ page: 1, page_size: 100 }),
  ]);

  // pipelines.list may return an array or { items: [...] } depending on API version
  let templates: import('@zerna/sdk').PipelineTemplate[] = [];
  if (templatesRes.status === 'fulfilled') {
    const raw = templatesRes.value;
    templates = Array.isArray(raw) ? raw : (raw.items ?? []);
    templates = [...templates].sort((left, right) => {
      const leftRec = Boolean(left.recommended);
      const rightRec = Boolean(right.recommended);
      if (leftRec !== rightRec) return leftRec ? -1 : 1;
      return left.name.localeCompare(right.name) || left.version.localeCompare(right.version);
    });
  }
  const datasets = datasetsRes.status === 'fulfilled' ? datasetsRes.value.items : [];

  return (
    <div>
      <div className="mb-6">
        <Link href="/runs" className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to runs
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">New run</h1>
        <p className="text-sm text-gray-500 mt-1">
          Select a dataset version and pipeline. scRNA-seq Standard v1.7.0 is the recommended
          workflow and is selected by default when you start a new run.
        </p>
      </div>

      {templates.length === 0 && (
        <div className="mb-4 rounded-md bg-yellow-50 border border-yellow-200 p-4 text-sm text-yellow-800">
          No pipeline templates found. Create a template before starting a run.
        </div>
      )}

      {datasets.length === 0 && (
        <div className="mb-4 rounded-md bg-yellow-50 border border-yellow-200 p-4 text-sm text-yellow-800">
          No datasets found.{' '}
          <Link href="/datasets/upload" className="underline">
            Upload a dataset
          </Link>{' '}
          first.
        </div>
      )}

      <RunCreateForm templates={templates} datasets={datasets} />
    </div>
  );
}
