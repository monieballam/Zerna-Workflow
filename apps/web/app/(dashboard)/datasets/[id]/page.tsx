import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { createServerClient } from '@/lib/api';
import type { DatasetVersionSummary, Run } from '@zerna/sdk';
import { formatDateTime } from '@/lib/dates';
import DatasetDeleteButton from '@/components/datasets/DatasetDeleteButton';

export const metadata: Metadata = {
  title: 'Dataset Details',
};

interface PageProps {
  params: Promise<{ id: string }>;
}

const STATUS_COLORS: Record<string, string> = {
  queued: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-800',
};

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

function VersionRow({ v }: { v: DatasetVersionSummary }) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 text-sm font-mono text-gray-700">{v.version}</td>
      <td className="px-4 py-3 text-sm text-gray-700">{v.file_format ?? '—'}</td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700">{formatNumber(v.cell_count)}</td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700">{formatNumber(v.gene_count)}</td>
      <td className="px-4 py-3 text-sm text-gray-500">{formatDateTime(v.created_at)}</td>
    </tr>
  );
}

function RunRow({ run }: { run: Run }) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3">
        <Link
          href={`/runs/${run.id}`}
          className="text-sm font-mono text-blue-600 hover:text-blue-800"
        >
          {run.id.slice(0, 8)}…
        </Link>
      </td>
      <td className="px-4 py-3">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            STATUS_COLORS[run.status] ?? 'bg-gray-100 text-gray-800'
          }`}
        >
          {run.status}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {run.started_at ? formatDateTime(run.started_at) : '—'}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {run.completed_at ? formatDateTime(run.completed_at) : '—'}
      </td>
      <td className="px-4 py-3 text-right">
        <Link
          href={`/runs/${run.id}`}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          View
        </Link>
      </td>
    </tr>
  );
}

export default async function DatasetDetailPage({ params }: PageProps) {
  const { id } = await params;
  const client = createServerClient();

  let dataset;
  try {
    dataset = await client.datasets.get(id);
  } catch {
    notFound();
  }

  let runs: Run[] = [];
  try {
    const runsResult = await client.runs.list({ dataset_id: id, page: 1, page_size: 100 });
    runs = runsResult.items;
  } catch {
    // Non-fatal — show empty runs list
  }

  const latestVersion = dataset.versions[dataset.versions.length - 1];
  const metadataEntries = Object.entries(dataset.metadata ?? {});

  return (
    <div className="max-w-4xl space-y-6">
      {/* Breadcrumb + header */}
      <div>
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-2">
          <Link href="/datasets" className="hover:text-gray-700">
            Datasets
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-gray-900 font-medium">{dataset.name}</span>
        </div>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{dataset.name}</h1>
            {dataset.description && <p className="mt-1 text-gray-500">{dataset.description}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <DatasetDeleteButton datasetId={dataset.id} datasetName={dataset.name} />
            {latestVersion && (
              <Link
                href={`/runs/new?dataset_version_id=${latestVersion.id}`}
                className="btn-primary shrink-0"
              >
                Create Run
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'Cells', value: formatNumber(latestVersion?.cell_count) },
          { label: 'Genes', value: formatNumber(latestVersion?.gene_count) },
          { label: 'Versions', value: String(dataset.versions.length) },
          { label: 'Runs', value: String(runs.length) },
        ].map(({ label, value }) => (
          <div key={label} className="card p-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
            <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      {/* Metadata */}
      {metadataEntries.length > 0 && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Metadata</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            {metadataEntries.map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-gray-500">{k}</dt>
                <dd className="text-sm text-gray-900 font-medium">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* Versions */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Versions</h2>
        <div className="card overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                {['Version', 'Format', 'Cells', 'Genes', 'Created'].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {dataset.versions.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-gray-400">
                    No versions yet.
                  </td>
                </tr>
              ) : (
                dataset.versions.map((v) => <VersionRow key={v.id} v={v} />)
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Runs */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Runs</h2>
        <div className="card overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                {['Run ID', 'Status', 'Started', 'Completed', ''].map((h, i) => (
                  <th
                    key={i}
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-gray-400">
                    No runs yet.{' '}
                    {latestVersion && (
                      <Link
                        href={`/runs/new?dataset_version_id=${latestVersion.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        Create the first run.
                      </Link>
                    )}
                  </td>
                </tr>
              ) : (
                runs.map((r) => <RunRow key={r.id} run={r} />)
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
