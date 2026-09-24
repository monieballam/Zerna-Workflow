import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Home',
};

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-14">
      {/* A. Hero */}
      <section className="rounded-2xl border border-gray-200 bg-white px-6 py-10 shadow-sm sm:px-10 sm:py-12">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          Single-cell analysis workspace
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-gray-600">
          Upload datasets, run reproducible analysis pipelines, review annotated results, and export
          artifacts.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/datasets/upload" className="btn-secondary">
            Upload dataset
          </Link>
          <Link href="/runs/new" className="btn-primary">
            Start new run
          </Link>
          <Link href="/runs" className="btn-secondary">
            View runs
          </Link>
        </div>
      </section>

      {/* B. Workflow summary */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900">How it works</h2>
        <p className="mt-1 text-sm text-gray-500">
          From raw data to exports in a few guided steps.
        </p>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <WorkflowStep
            step={1}
            title="Upload data"
            description="Add expression data and metadata so it is ready for pipeline runs."
          />
          <WorkflowStep
            step={2}
            title="Configure run"
            description="Choose a pipeline template, dataset version, and parameters for your biology."
          />
          <WorkflowStep
            step={3}
            title="Execute"
            description="The platform runs QC, processing, clustering, and optional downstream steps with checkpoints."
          />
          <WorkflowStep
            step={4}
            title="Review results"
            description="Inspect run status, embeddings, tables, and plots from the run detail and explore views."
          />
          <WorkflowStep
            step={5}
            title="Export artifacts"
            description="Download processed outputs, reports, and sidecar files stored with each run."
          />
        </div>
      </section>

      {/* C. Outcomes */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900">What you get from a completed run</h2>
        <p className="mt-1 text-sm text-gray-500">
          Outputs depend on your template and options; typical runs include the following.
        </p>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <OutcomeCard
            title="Processed dataset"
            body="A processed AnnData object (main artifact) reflecting QC, normalization, and the steps your template applied."
          />
          <OutcomeCard
            title="QC summaries"
            body="QC metrics and summary sidecars you can inspect alongside the run."
          />
          <OutcomeCard
            title="Embeddings and clusters"
            body="Low-dimensional embeddings and cluster assignments for exploration in the run UI."
          />
          <OutcomeCard
            title="Cell type annotations"
            body="Annotation columns and hierarchy-friendly labels when your pipeline includes an annotation step."
          />
          <OutcomeCard
            title="Differential expression and pathways"
            body="DE tables, pathway scores, and related exports when those steps are enabled on your template."
          />
          <OutcomeCard
            title="Downloadable artifacts and provenance"
            body="Files attached to the run plus template and parameter context for reproducibility."
          />
        </ul>
      </section>

      {/* D. Navigation map */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900">Where to go next</h2>
        <p className="mt-1 text-sm text-gray-500">
          Match what you want to do with a destination in the app.
        </p>
        <div className="mt-6 card divide-y divide-gray-100 overflow-hidden">
          <NavRow
            goal="Manage datasets"
            href="/datasets"
            hint="List, open, and upload dataset versions."
          />
          <NavRow
            goal="Start a new run"
            href="/runs/new"
            hint="Pick a template and dataset, then launch."
          />
          <NavRow goal="View all runs" href="/runs" hint="Filter by status and open any run." />
          <NavRow
            goal="Open results"
            href="/runs"
            hint="Choose a run for progress, explore, artifacts, and downloads."
          />
          <NavRow
            goal="Browse pipelines"
            href="/pipelines"
            hint="Review templates and optional builder flows."
          />
        </div>
      </section>
    </div>
  );
}

function WorkflowStep({
  step,
  title,
  description,
}: {
  step: number;
  title: string;
  description: string;
}) {
  return (
    <div className="card p-5 flex flex-col">
      <span className="text-xs font-semibold uppercase tracking-wide text-primary-600">
        Step {step}
      </span>
      <h3 className="mt-2 text-sm font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-600">{description}</p>
    </div>
  );
}

function OutcomeCard({ title, body }: { title: string; body: string }) {
  return (
    <li className="card p-5 list-none">
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-600">{body}</p>
    </li>
  );
}

function NavRow({ goal, href, hint }: { goal: string; href: string; hint: string }) {
  return (
    <div className="flex flex-col gap-1 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm font-medium text-gray-900">{goal}</p>
        <p className="text-sm text-gray-500">{hint}</p>
      </div>
      <Link
        href={href}
        className="mt-2 shrink-0 text-sm font-medium text-primary-600 hover:text-primary-700 sm:mt-0"
      >
        Go
        <span className="sr-only"> to {goal}</span>
      </Link>
    </div>
  );
}
