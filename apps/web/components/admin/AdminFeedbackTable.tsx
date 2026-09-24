import Link from 'next/link';
import type { AdminFeedback } from '@zerna/sdk';

interface AdminFeedbackTableProps {
  items: AdminFeedback[];
}

function formatParameters(parameters: Record<string, unknown> | null): string {
  if (!parameters || Object.keys(parameters).length === 0) {
    return 'No run parameters captured.';
  }
  return JSON.stringify(parameters, null, 2);
}

export default function AdminFeedbackTable({ items }: AdminFeedbackTableProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        No feedback has been submitted yet.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Submitted
            </th>
            <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              User
            </th>
            <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Target
            </th>
            <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Feedback
            </th>
            <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Run parameters
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <td className="px-5 py-4 text-sm text-gray-500">
                {new Date(item.created_at).toLocaleString()}
              </td>
              <td className="px-5 py-4 text-sm text-gray-900">{item.user_email}</td>
              <td className="px-5 py-4 text-sm text-gray-700">
                <p className="font-medium text-gray-900">
                  {item.scope === 'run' ? 'Run' : 'System'}
                </p>
                {item.dataset_name_snapshot && (
                  <p className="mt-1 text-gray-500">{item.dataset_name_snapshot}</p>
                )}
                {item.run_id ? (
                  <Link
                    href={`/runs/${item.run_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex text-blue-600 hover:text-blue-800"
                  >
                    Open run
                  </Link>
                ) : (
                  <p className="mt-1 text-gray-400">No run attached</p>
                )}
              </td>
              <td className="px-5 py-4 text-sm text-gray-700">
                <p className="font-medium text-gray-900">
                  {item.title?.trim() || `${item.category} feedback`}
                </p>
                <p className="mt-1 text-xs uppercase tracking-wide text-gray-500">
                  {item.category}
                </p>
                <details className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                  <summary className="cursor-pointer text-sm font-medium text-gray-700">
                    View message
                  </summary>
                  <p className="mt-3 whitespace-pre-wrap text-sm text-gray-700">{item.message}</p>
                </details>
              </td>
              <td className="px-5 py-4 text-sm text-gray-700">
                <p className="text-xs uppercase tracking-wide text-gray-500">
                  {item.run_status_snapshot
                    ? `Run status: ${item.run_status_snapshot}`
                    : 'No run snapshot'}
                </p>
                <details className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                  <summary className="cursor-pointer text-sm font-medium text-gray-700">
                    View parameters
                  </summary>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-gray-700">
                    {formatParameters(item.run_parameters_snapshot)}
                  </pre>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
