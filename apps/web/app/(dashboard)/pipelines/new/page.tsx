import type { Metadata } from 'next';
import Link from 'next/link';
import { createServerClient } from '@/lib/api';
import { getFallbackPipelineCatalog } from '@/lib/pipeline-catalog';
import PipelineTemplateEditor from '@/components/pipelines/PipelineTemplateEditor';

export const metadata: Metadata = {
  title: 'New Pipeline Template',
};

export default async function NewPipelineTemplatePage() {
  const client = createServerClient();

  let catalog = getFallbackPipelineCatalog();
  let catalogWarning: string | null = null;
  try {
    const response = await client.pipelines.getCatalog();
    catalog = response.methods;
  } catch {
    catalogWarning = 'Method catalog API unavailable. Using local fallback method definitions.';
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/pipelines" className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to templates
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">New Pipeline Template</h1>
        <p className="mt-1 text-sm text-gray-500">
          Build a reusable pipeline definition with explicit steps, parameters, and versioning.
        </p>
      </div>

      {catalogWarning && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          {catalogWarning}
        </div>
      )}

      <PipelineTemplateEditor catalog={catalog} />
    </div>
  );
}
