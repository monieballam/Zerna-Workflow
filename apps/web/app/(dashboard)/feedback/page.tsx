import type { Metadata } from 'next';
import Link from 'next/link';
import { createServerClient } from '@/lib/api';
import FeedbackForm from '@/components/feedback/FeedbackForm';

export const metadata: Metadata = { title: 'Feedback' };

interface PageProps {
  searchParams: Promise<{ runId?: string }>;
}

export default async function FeedbackPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const client = createServerClient();

  let runs: Awaited<ReturnType<typeof client.runs.list>>['items'] = [];
  let feedback = {
    items: [] as Awaited<ReturnType<typeof client.feedback.list>>['items'],
    total: 0,
  };

  const [runsResult, feedbackResult] = await Promise.allSettled([
    client.runs.list({ page: 1, page_size: 100 }),
    client.feedback.list({ page: 1, page_size: 20 }),
  ]);

  if (runsResult.status === 'fulfilled') {
    runs = runsResult.value.items;
  }
  if (feedbackResult.status === 'fulfilled') {
    feedback = feedbackResult.value;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Feedback</h1>
        <p className="mt-2 max-w-3xl text-sm text-gray-500">
          Capture product issues, scientific concerns, and run-specific notes in one place. Run
          feedback keeps the associated dataset and parameter snapshot so admins can review exactly
          what was executed.
        </p>
      </div>

      <FeedbackForm
        runs={runs.map((run) => ({
          id: run.id,
          status: run.status,
          datasetName: run.dataset_name,
          createdAt: run.created_at,
        }))}
        defaultRunId={params.runId}
      />

      <section className="card p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Recent submissions</h2>
            <p className="mt-1 text-sm text-gray-500">
              Your most recent feedback in this organization.
            </p>
          </div>
          <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
            {feedback.total} total
          </span>
        </div>

        {feedback.items.length === 0 ? (
          <p className="mt-4 text-sm text-gray-500">No feedback submitted yet.</p>
        ) : (
          <div className="mt-4 divide-y divide-gray-100">
            {feedback.items.map((item) => (
              <div key={item.id} className="py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                    {item.scope}
                  </span>
                  <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                    {item.category}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-gray-900">
                  {item.title?.trim() || 'Untitled feedback'}
                </p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-gray-600">{item.message}</p>
                {item.run_id && (
                  <div className="mt-2">
                    <Link
                      href={`/runs/${item.run_id}`}
                      className="text-sm font-medium text-blue-600 hover:text-blue-800"
                    >
                      Open run
                    </Link>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
