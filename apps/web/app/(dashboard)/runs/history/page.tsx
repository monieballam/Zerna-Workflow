import type { Metadata } from 'next';
import Link from 'next/link';
import RunHistory from '@/components/runs/RunHistory';

export const metadata: Metadata = { title: 'Previous Runs' };

export default function PreviousRunsPage() {
  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Previous Runs</h1>
          <p className="text-sm text-gray-500 mt-1">Search, load, and replay past pipeline runs.</p>
        </div>
        <Link href="/runs" className="text-sm text-blue-600 hover:text-blue-800 font-medium">
          ← Back to runs
        </Link>
      </div>

      <RunHistory />
    </div>
  );
}
