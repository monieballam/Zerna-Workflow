import type { Metadata } from 'next';
import Link from 'next/link';
import UploadForm from '@/components/datasets/UploadForm';

export const metadata: Metadata = {
  title: 'Upload Dataset',
};

export default function UploadDatasetPage() {
  return (
    <div className="max-w-2xl">
      <div className="flex items-center gap-2 mb-6">
        <Link href="/datasets" className="text-sm text-gray-500 hover:text-gray-700">
          Datasets
        </Link>
        <span className="text-gray-300">/</span>
        <h1 className="text-2xl font-bold text-gray-900">Upload Dataset</h1>
      </div>

      <div className="card p-6">
        <UploadForm />
      </div>
    </div>
  );
}
