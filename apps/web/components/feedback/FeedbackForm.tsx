'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

type FeedbackRunOption = {
  id: string;
  status: string;
  datasetName: string | null;
  createdAt: string;
};

interface FeedbackFormProps {
  runs: FeedbackRunOption[];
  defaultRunId?: string;
}

export default function FeedbackForm({ runs, defaultRunId }: FeedbackFormProps) {
  const router = useRouter();
  const [scope, setScope] = useState<'system' | 'run'>(defaultRunId ? 'run' : 'system');
  const [category, setCategory] = useState('other');
  const [runId, setRunId] = useState(defaultRunId ?? '');
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (scope === 'run' && !runId) {
      setError('Choose a run when submitting run-specific feedback.');
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch('/api/proxy/v1/feedback', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          scope,
          category,
          run_id: scope === 'run' ? runId : undefined,
          title: title.trim() || undefined,
          message: message.trim(),
        }),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Feedback submission failed (${response.status})`);
      }

      setSuccess('Feedback submitted.');
      setTitle('');
      setMessage('');
      router.refresh();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Feedback submission failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Submit feedback</h2>
        <p className="mt-1 text-sm text-gray-500">
          Send system-wide product feedback or attach a note to one specific run for admin review.
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
          {success}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-gray-700">Feedback scope</span>
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as 'system' | 'run')}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
          >
            <option value="system">Whole system</option>
            <option value="run">Specific run</option>
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-gray-700">Category</span>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
          >
            <option value="bug">Bug</option>
            <option value="science">Scientific concern</option>
            <option value="ux">UX / explorer</option>
            <option value="performance">Performance</option>
            <option value="feature">Feature request</option>
            <option value="other">Other</option>
          </select>
        </label>
      </div>

      {scope === 'run' && (
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-gray-700">Run</span>
          <select
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
          >
            <option value="">Choose a run</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id.slice(0, 8)}... {run.datasetName ? `• ${run.datasetName}` : ''} •{' '}
                {run.status}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium text-gray-700">Title</span>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Short summary"
          className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium text-gray-700">Details</span>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Describe what happened, what you expected, and any scientific or technical concerns."
          rows={6}
          required
          className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
        />
      </label>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting || message.trim().length < 5}
          className="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Submitting…' : 'Submit feedback'}
        </button>
      </div>
    </form>
  );
}
