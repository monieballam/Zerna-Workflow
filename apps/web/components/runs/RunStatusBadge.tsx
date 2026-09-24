import type { RunStatus } from '@zerna/sdk';

const STATUS_STYLES: Record<RunStatus, string> = {
  queued: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-800',
};

interface Props {
  status: RunStatus;
}

export default function RunStatusBadge({ status }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-800'
      }`}
    >
      {status === 'running' && (
        <span
          className="mr-1.5 h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse"
          aria-hidden="true"
        />
      )}
      {status}
    </span>
  );
}
