import type { Metadata } from 'next';
import Link from 'next/link';
import { createServerClient } from '@/lib/api';
import {
  deactivatePipelineTemplateAction,
  syncDefaultTemplatesAction,
} from '@/lib/pipeline-actions';

export const metadata: Metadata = {
  title: 'Pipeline Templates',
};

interface PageProps {
  searchParams: Promise<{
    error?: string;
  }>;
}

function normalizeTemplates(
  raw:
    | import('@zerna/sdk').PipelineTemplate[]
    | { items: import('@zerna/sdk').PipelineTemplate[]; total: number }
) {
  return Array.isArray(raw) ? raw : (raw.items ?? []);
}

function sortTemplates(templates: import('@zerna/sdk').PipelineTemplate[]) {
  return [...templates].sort((left, right) => {
    const leftRec = Boolean(left.recommended);
    const rightRec = Boolean(right.recommended);
    if (leftRec !== rightRec) return leftRec ? -1 : 1;
    const leftDep = Boolean(left.deprecated);
    const rightDep = Boolean(right.deprecated);
    if (leftDep !== rightDep) return leftDep ? 1 : -1;
    return left.name.localeCompare(right.name) || left.version.localeCompare(right.version);
  });
}

function getTemplateDescription(template: import('@zerna/sdk').PipelineTemplate): string {
  const metadata = (template.definition?.metadata as Record<string, unknown> | undefined) ?? {};
  return typeof metadata.description === 'string' ? metadata.description : 'No description';
}

function methodCount(template: import('@zerna/sdk').PipelineTemplate): number {
  const methods = template.definition?.methods;
  return Array.isArray(methods) ? methods.length : 0;
}

export default async function PipelineTemplatesPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const client = createServerClient();

  const [activeRes, inactiveRes] = await Promise.allSettled([
    client.pipelines.list({
      page: 1,
      page_size: 100,
      is_active: true,
      include_hidden_in_picker: true,
    }),
    client.pipelines.list({
      page: 1,
      page_size: 100,
      is_active: false,
      include_hidden_in_picker: true,
    }),
  ]);

  const activeTemplates =
    activeRes.status === 'fulfilled' ? sortTemplates(normalizeTemplates(activeRes.value)) : [];
  const inactiveTemplates =
    inactiveRes.status === 'fulfilled' ? sortTemplates(normalizeTemplates(inactiveRes.value)) : [];

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline Templates</h1>
          <p className="mt-1 text-sm text-gray-500">
            Create reusable run templates, clone them into new versions, and keep the seeded
            defaults in sync with the full analysis pipeline.
          </p>
        </div>
        <div className="flex gap-3">
          <form action={syncDefaultTemplatesAction}>
            <button type="submit" className="btn-secondary">
              Sync Defaults
            </button>
          </form>
          <Link href="/pipelines/new" className="btn-primary">
            New Template
          </Link>
        </div>
      </div>

      {params.error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {params.error}
        </div>
      )}

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Active Versions</h2>
          <p className="text-sm text-gray-500">{activeTemplates.length} templates</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {activeTemplates.map((template) => {
            const metadata =
              (template.definition?.metadata as Record<string, unknown> | undefined) ?? {};
            const recommended = Boolean(template.recommended ?? metadata.recommended);
            const deprecated = Boolean(template.deprecated ?? metadata.deprecated);
            return (
              <article
                key={template.id}
                className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold text-gray-900">{template.name}</h3>
                      {recommended && (
                        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                          Recommended
                        </span>
                      )}
                      {deprecated && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
                          Deprecated
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-gray-500">v{template.version}</p>
                  </div>
                  <div className="flex gap-2">
                    <Link href={`/pipelines/${template.id}/edit`} className="btn-secondary">
                      Clone / Edit
                    </Link>
                    <form action={deactivatePipelineTemplateAction.bind(null, template.id)}>
                      <button type="submit" className="btn-secondary">
                        Deactivate
                      </button>
                    </form>
                  </div>
                </div>

                <p className="mt-4 text-sm text-gray-600">{getTemplateDescription(template)}</p>

                <dl className="mt-4 grid grid-cols-3 gap-3 rounded-lg bg-gray-50 p-4 text-sm">
                  <div>
                    <dt className="text-gray-500">Steps</dt>
                    <dd className="mt-1 font-medium text-gray-900">{methodCount(template)}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Status</dt>
                    <dd className="mt-1 font-medium text-gray-900">Active</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Created</dt>
                    <dd className="mt-1 font-medium text-gray-900">
                      {new Date(template.created_at).toLocaleDateString()}
                    </dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
        {activeTemplates.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white p-10 text-center text-sm text-gray-500">
            No active templates found. Sync the seeded defaults or create a new template.
          </div>
        )}
      </section>

      {inactiveTemplates.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Inactive Versions</h2>
            <p className="text-sm text-gray-500">{inactiveTemplates.length} versions</p>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {inactiveTemplates.map((template) => (
              <article
                key={template.id}
                className="rounded-xl border border-gray-200 bg-gray-50 p-6"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">{template.name}</h3>
                    <p className="mt-1 text-sm text-gray-500">v{template.version}</p>
                  </div>
                  <Link href={`/pipelines/${template.id}/edit`} className="btn-secondary">
                    Clone / Edit
                  </Link>
                </div>
                <p className="mt-4 text-sm text-gray-600">{getTemplateDescription(template)}</p>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
