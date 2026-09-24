import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ApiResponseError } from '@zerna/sdk';
import { createServerClient } from '@/lib/api';
import { getFallbackPipelineCatalog } from '@/lib/pipeline-catalog';
import PipelineTemplateEditor from '@/components/pipelines/PipelineTemplateEditor';

export const metadata: Metadata = {
  title: 'Clone Pipeline Template',
};

interface PageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function EditPipelineTemplatePage({ params }: PageProps) {
  const { id } = await params;
  const client = createServerClient();

  let template: import('@zerna/sdk').PipelineTemplate | null = null;
  let loadError: string | null = null;

  try {
    template = await client.pipelines.get(id);
  } catch (error: unknown) {
    if (error instanceof ApiResponseError && error.status === 404) {
      notFound();
    }

    loadError =
      error instanceof Error ? error.message : 'Failed to load the selected pipeline template.';
  }

  if (!template) {
    return (
      <div className="space-y-6">
        <div>
          <Link href="/pipelines" className="text-sm text-gray-500 hover:text-gray-700">
            ← Back to templates
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">Clone Template Version</h1>
        </div>
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {loadError ?? 'Failed to load the selected pipeline template.'}
        </div>
      </div>
    );
  }

  let catalog = getFallbackPipelineCatalog();
  let catalogWarning: string | null = null;
  try {
    const catalogResponse = await client.pipelines.getCatalog();
    catalog = catalogResponse.methods;
  } catch {
    catalogWarning = 'Method catalog API unavailable. Using local fallback method definitions.';
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/pipelines" className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to templates
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Clone Template Version</h1>
        <p className="mt-1 text-sm text-gray-500">
          Editing creates a new version. The existing template remains intact until you choose to
          deactivate it.
        </p>
      </div>

      {catalogWarning && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          {catalogWarning}
        </div>
      )}

      <PipelineTemplateEditor catalog={catalog} initialTemplate={template} />
    </div>
  );
}
