'use client';

import Link from 'next/link';
import { useState, useTransition } from 'react';
import type { Run, Artifact } from '@zerna/sdk';
import RunStatusBadge from './RunStatusBadge';
import { useSingleRunUpdates } from '@/lib/useRunUpdates';
import { cancelRunAction } from '@/lib/run-actions';
import { formatDateTime } from '@/lib/dates';
import {
  type ParameterSectionConfig,
  METHOD_INFO,
  PARAMETER_SECTIONS,
  formatParameterValue,
  getParameterLabel,
  isFieldVisible,
} from '@/lib/pipeline-parameter-presentation';

interface Props {
  initialRun: Run;
  artifacts: Artifact[];
}

type RunProgressStep = {
  step_name: string;
  label?: string | null;
  status?: string | null;
  summary?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
};

type RunProgress = {
  current_step?: string | null;
  current_step_label?: string | null;
  current_step_started_at?: string | null;
  total_steps?: number | null;
  progress_percent?: number | null;
  completed_steps?: string[];
  step_summaries?: RunProgressStep[];
  updated_at?: string | null;
};

type ParameterDisplay = {
  name: string;
  label: string;
  value: string;
};

type RunStageSection = Omit<ParameterSectionConfig, 'fields'> & {
  fields: ParameterDisplay[];
  steps: RunProgressStep[];
};

type StageOverviewStatus = 'done' | 'active' | 'failed' | 'skipped' | 'pending';

type StageOverviewItem = {
  id: string;
  label: string;
  status: StageOverviewStatus;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getRunProgress(parameters: Record<string, unknown>): RunProgress | null {
  const progress = parameters.progress;
  if (!isRecord(progress)) return null;

  const stepSummaries = Array.isArray(progress.step_summaries)
    ? progress.step_summaries.filter(
        (item): item is RunProgressStep => isRecord(item) && typeof item.step_name === 'string'
      )
    : [];

  const completedSteps = Array.isArray(progress.completed_steps)
    ? progress.completed_steps.filter((item): item is string => typeof item === 'string')
    : [];

  return {
    current_step: typeof progress.current_step === 'string' ? progress.current_step : null,
    current_step_label:
      typeof progress.current_step_label === 'string'
        ? progress.current_step_label
        : typeof progress.current_step === 'string'
          ? progress.current_step
          : null,
    current_step_started_at:
      typeof progress.current_step_started_at === 'string'
        ? progress.current_step_started_at
        : null,
    total_steps: typeof progress.total_steps === 'number' ? progress.total_steps : null,
    progress_percent:
      typeof progress.progress_percent === 'number' ? progress.progress_percent : null,
    completed_steps: completedSteps,
    step_summaries: stepSummaries,
    updated_at: typeof progress.updated_at === 'string' ? progress.updated_at : null,
  };
}

function hasOwnProperty(object: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function getStepLabel(step: RunProgressStep): string {
  return step.label ?? METHOD_INFO[step.step_name]?.label ?? step.step_name;
}

function normalizeStepStatus(status: string | null | undefined): string | null {
  return typeof status === 'string' ? status.toLowerCase() : null;
}

function buildRunStageSections(
  parameters: Record<string, unknown>,
  progressEntries: RunProgressStep[]
): RunStageSection[] {
  const parameterValues = Object.fromEntries(
    Object.entries(parameters).filter(([key]) => key !== 'progress' && !key.startsWith('_'))
  );
  const mappedStepNames = new Set<string>();
  const mappedFieldNames = new Set(PARAMETER_SECTIONS.flatMap((section) => section.fields));

  const sections = PARAMETER_SECTIONS.map((section) => {
    const fields = section.fields
      .filter(
        (fieldName) =>
          hasOwnProperty(parameterValues, fieldName) && isFieldVisible(fieldName, parameterValues)
      )
      .map((fieldName) => ({
        name: fieldName,
        label: getParameterLabel(fieldName),
        value: formatParameterValue(parameterValues[fieldName]),
      }));

    const steps = progressEntries.filter((entry) => section.methods?.includes(entry.step_name));
    for (const step of steps) mappedStepNames.add(step.step_name);

    if (fields.length === 0 && steps.length === 0) return null;
    return { ...section, fields, steps };
  }).filter((section): section is RunStageSection => Boolean(section));

  const additionalFields = Object.entries(parameterValues)
    .filter(([fieldName]) => !mappedFieldNames.has(fieldName))
    .map(([fieldName, value]) => ({
      name: fieldName,
      label: getParameterLabel(fieldName),
      value: formatParameterValue(value),
    }));

  if (additionalFields.length > 0) {
    sections.push({
      id: 'additional-parameters',
      title: 'Additional Parameters',
      description: 'Template-specific settings that do not map to a standard pipeline stage.',
      fields: additionalFields,
      steps: [],
      fullWidth: true,
    });
  }

  const additionalSteps = progressEntries.filter((entry) => !mappedStepNames.has(entry.step_name));
  if (additionalSteps.length > 0) {
    sections.push({
      id: 'additional-steps',
      title: 'Additional Pipeline Steps',
      description: 'Executed steps that do not map to the standard pipeline stage layout.',
      fields: [],
      steps: additionalSteps,
      fullWidth: true,
    });
  }

  return sections;
}

function buildStageOverviewItems(
  sections: RunStageSection[],
  progress: RunProgress | null
): StageOverviewItem[] {
  const completedSteps = new Set(progress?.completed_steps ?? []);

  return sections
    .filter((section) => section.id !== 'additional-parameters')
    .map((section) => {
      const normalizedStatuses = section.steps
        .map((step) => normalizeStepStatus(step.status))
        .filter((status): status is string => Boolean(status));
      const sectionMethods = Array.isArray(section.methods) ? section.methods : [];

      let status: StageOverviewStatus = 'pending';

      if (
        typeof progress?.current_step === 'string' &&
        (sectionMethods.includes(progress.current_step) ||
          section.steps.some((step) => step.step_name === progress.current_step))
      ) {
        status = 'active';
      } else if (normalizedStatuses.includes('failed')) {
        status = 'failed';
      } else if (
        normalizedStatuses.includes('completed') ||
        sectionMethods.some((method) => completedSteps.has(method))
      ) {
        status = 'done';
      } else if (normalizedStatuses.includes('skipped')) {
        status = 'skipped';
      }

      return {
        id: section.id,
        label: section.title,
        status,
      };
    });
}

function StageOverviewBadge({ item }: { item: StageOverviewItem }) {
  const styles: Record<StageOverviewStatus, string> = {
    done: 'border-green-200 bg-green-50 text-green-700',
    active: 'border-blue-200 bg-blue-50 text-blue-700',
    failed: 'border-red-200 bg-red-50 text-red-700',
    skipped: 'border-amber-200 bg-amber-50 text-amber-700',
    pending: 'border-gray-200 bg-gray-50 text-gray-500',
  };

  const icons: Record<StageOverviewStatus, string> = {
    done: '✓',
    active: '●',
    failed: '!',
    skipped: '⊘',
    pending: '○',
  };

  return (
    <span
      data-testid={`stage-overview-${item.id}`}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${styles[item.status]}`}
      aria-label={`${item.label}: ${item.status}`}
    >
      <span aria-hidden="true">{icons[item.status]}</span>
      {item.label}
    </span>
  );
}

function ProgressStepBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const styles =
    normalized === 'completed'
      ? 'border-green-200 bg-green-50 text-green-700'
      : normalized === 'failed'
        ? 'border-red-200 bg-red-50 text-red-700'
        : normalized === 'skipped'
          ? 'border-amber-200 bg-amber-50 text-amber-700'
          : 'border-gray-200 bg-gray-50 text-gray-600';

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {normalized}
    </span>
  );
}

function ProgressStepCard({ entry }: { entry: RunProgressStep }) {
  const [expanded, setExpanded] = useState(entry.status?.toLowerCase() !== 'completed');
  const hasTimingDetails =
    Boolean(entry.started_at) ||
    Boolean(entry.completed_at) ||
    typeof entry.duration_seconds === 'number';
  const canExpand = hasTimingDetails;
  const detailId = `run-step-${entry.step_name}`;

  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-start gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900">{getStepLabel(entry)}</p>
              {entry.summary && <p className="mt-1 text-sm text-gray-600">{entry.summary}</p>}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ProgressStepBadge status={entry.status ?? 'completed'} />
          {canExpand && (
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={detailId}
              onClick={() => setExpanded((value) => !value)}
              className="rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              {expanded ? 'Hide details' : 'Show details'}
            </button>
          )}
        </div>
      </div>
      {expanded && hasTimingDetails && (
        <div
          id={detailId}
          className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-gray-100 pt-2 text-xs text-gray-400"
        >
          {entry.started_at && <span>Started {formatDateTime(entry.started_at)}</span>}
          {entry.completed_at && <span>Finished {formatDateTime(entry.completed_at)}</span>}
          {typeof entry.duration_seconds === 'number' && (
            <span>Duration {entry.duration_seconds.toFixed(1)}s</span>
          )}
        </div>
      )}
    </div>
  );
}

function StageSections({
  currentStep,
  sections,
}: {
  currentStep?: string | null;
  sections: RunStageSection[];
}) {
  return (
    <div className="mt-5 space-y-4">
      {sections.map((section) => {
        const isCurrentSection =
          typeof currentStep === 'string' &&
          Array.isArray(section.methods) &&
          section.methods.includes(currentStep);

        return (
          <section
            key={section.id}
            className={`rounded-xl border p-4 ${
              isCurrentSection ? 'border-blue-200 bg-blue-50/40' : 'border-gray-200 bg-gray-50'
            }`}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-900">{section.title}</h3>
                <p className="mt-1 text-xs text-gray-500">{section.description}</p>
              </div>
              <div className="flex items-center gap-2">
                {isCurrentSection && (
                  <span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                    Active
                  </span>
                )}
                {section.steps.length > 0 && (
                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-500">
                    {section.steps.length} step{section.steps.length === 1 ? '' : 's'}
                  </span>
                )}
              </div>
            </div>

            {section.fields.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Settings used
                </p>
                <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {section.fields.map((field) => (
                    <div
                      key={field.name}
                      className="rounded-lg border border-gray-200 bg-white px-3 py-2"
                    >
                      <dt className="text-xs font-medium text-gray-500">{field.label}</dt>
                      <dd className="mt-1 break-all font-mono text-sm text-gray-900">
                        {field.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            {section.steps.length > 0 && (
              <div className="mt-4 space-y-3">
                {section.steps.map((entry) => (
                  <ProgressStepCard key={entry.step_name} entry={entry} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

export default function RunDetail({ initialRun, artifacts }: Props) {
  const run = useSingleRunUpdates(initialRun);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [progressExpanded, setProgressExpanded] = useState(true);
  const [isPending, startTransition] = useTransition();

  function handleCancel() {
    startTransition(async () => {
      const result = await cancelRunAction(run.id);
      if (result.error) setCancelError(result.error);
    });
  }

  const progress = getRunProgress(run.parameters);
  const progressEntries = progress?.step_summaries ?? [];
  const softwareVersions = run.software_versions ? Object.entries(run.software_versions) : [];
  const stageSections = buildRunStageSections(run.parameters, progressEntries);
  const completedStepCount =
    progress?.completed_steps?.length ??
    progressEntries.filter((entry) => entry.status?.toLowerCase() === 'completed').length;
  const totalSteps = progress?.total_steps ?? null;
  const progressPercent =
    typeof progress?.progress_percent === 'number'
      ? Math.max(0, Math.min(100, Math.round(progress.progress_percent)))
      : totalSteps && totalSteps > 0
        ? Math.round((completedStepCount / totalSteps) * 100)
        : 0;
  const stageOverviewItems = buildStageOverviewItems(stageSections, progress);
  const showProgressCard =
    run.status === 'queued' ||
    run.status === 'running' ||
    progressEntries.length > 0 ||
    totalSteps != null;
  const showConfigurationCard = !showProgressCard && stageSections.length > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card p-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <RunStatusBadge status={run.status} />
              <span className="font-mono text-sm text-gray-500">{run.id}</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm mt-4">
              <div>
                <dt className="text-gray-500">Created</dt>
                <dd className="text-gray-900">{formatDateTime(run.created_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Started</dt>
                <dd className="text-gray-900">{formatDateTime(run.started_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Completed</dt>
                <dd className="text-gray-900">{formatDateTime(run.completed_at)}</dd>
              </div>
              {run.random_seed != null && (
                <div>
                  <dt className="text-gray-500">Random seed</dt>
                  <dd className="text-gray-900 font-mono">{run.random_seed}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="flex items-start gap-3">
            <Link
              href={`/feedback?runId=${run.id}`}
              className="rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Send feedback
            </Link>

            {run.status === 'completed' && (
              <Link
                href={`/runs/${run.id}/explore`}
                className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 transition-colors"
              >
                Open explorer
              </Link>
            )}

            {run.status === 'running' && (
              <div>
                <button
                  onClick={handleCancel}
                  disabled={isPending}
                  className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {isPending ? 'Cancelling…' : 'Cancel run'}
                </button>
                {cancelError && <p className="mt-1 text-xs text-red-600">{cancelError}</p>}
              </div>
            )}

            {run.status === 'failed' &&
              (run.dataset_deleted || !run.dataset_version_id ? (
                <span className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800">
                  Resume unavailable
                </span>
              ) : (
                <Link
                  href={`/runs/${run.id}/resume`}
                  className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 transition-colors"
                >
                  Resume with fixes
                </Link>
              ))}
          </div>
        </div>
      </div>

      {run.dataset_deleted && (
        <div className="card border-l-4 border-amber-400 bg-amber-50 p-5">
          <h2 className="text-sm font-semibold text-amber-900">Source dataset deleted</h2>
          <p className="mt-1 text-sm text-amber-800">
            This run remains viewable as a historical record, but it cannot be resumed from the
            original dataset anymore.
          </p>
        </div>
      )}

      {/* Error message */}
      {run.status === 'failed' && run.error_message && (
        <div className="card p-6 border-l-4 border-red-500">
          <h2 className="text-sm font-semibold text-red-700 mb-2">Run failed</h2>
          <p className="mb-3 text-xs text-red-600">
            Use <strong>Resume with fixes</strong> to adjust parameters and continue from the failed
            checkpoint instead of restarting the entire pipeline.
          </p>
          <pre className="text-xs text-red-600 whitespace-pre-wrap font-mono bg-red-50 rounded p-3 overflow-x-auto">
            {run.error_message}
          </pre>
        </div>
      )}

      {run.status === 'completed' && (
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-gray-700">Completed run outputs</h2>
          <p className="mt-2 text-sm text-gray-500">
            Results summaries, the embedding view, and all downloadable artifacts now live in the
            explorer workspace.
            {artifacts.length > 0
              ? ` ${artifacts.length} persisted artifact${artifacts.length === 1 ? ' is' : 's are'} available there.`
              : ''}
          </p>
          <div className="mt-4">
            <Link
              href={`/runs/${run.id}/explore`}
              className="inline-flex rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 transition-colors"
            >
              Open explorer workspace
            </Link>
          </div>
        </div>
      )}

      {showProgressCard && (
        <div className="card p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Pipeline steps</h2>
              <p className="mt-1 text-sm text-gray-500">
                {totalSteps != null
                  ? `${completedStepCount} of ${totalSteps} steps finished`
                  : 'Progress details will appear when execution begins.'}
              </p>
            </div>
            <div className="text-right">
              <p className="text-2xl font-semibold text-gray-900">{progressPercent}%</p>
              {progress?.updated_at && (
                <p className="text-xs text-gray-400">
                  Updated {formatDateTime(progress.updated_at)}
                </p>
              )}
            </div>
            <button
              type="button"
              aria-expanded={progressExpanded}
              onClick={() => setProgressExpanded((value) => !value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              {progressExpanded ? 'Collapse' : 'Expand'}
            </button>
          </div>

          {progressExpanded && (
            <>
              {stageOverviewItems.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Stage overview
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {stageOverviewItems.map((item) => (
                      <StageOverviewBadge key={item.id} item={item} />
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              {progress?.current_step_label ? (
                <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
                    Currently running
                  </p>
                  <p className="mt-1 text-sm font-medium text-blue-900">
                    {progress.current_step_label}
                  </p>
                  {progress.current_step_started_at && (
                    <p className="mt-1 text-xs text-blue-700">
                      Started {formatDateTime(progress.current_step_started_at)}
                    </p>
                  )}
                </div>
              ) : run.status === 'queued' ? (
                <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                  The run is queued. Step-by-step updates will appear here once execution starts.
                </div>
              ) : null}

              {stageSections.length > 0 && (
                <StageSections currentStep={progress?.current_step} sections={stageSections} />
              )}
            </>
          )}
        </div>
      )}

      {showConfigurationCard && (
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-gray-700">Pipeline configuration</h2>
          <p className="mt-1 text-sm text-gray-500">
            Settings are grouped by the pipeline stage they affect so you can review configuration
            without parsing the raw parameter payload.
          </p>
          <StageSections sections={stageSections} />
        </div>
      )}

      {/* Software versions */}
      {softwareVersions.length > 0 && (
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Software versions</h2>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            {softwareVersions.map(([pkg, version]) => (
              <div key={pkg}>
                <dt className="text-gray-500 font-mono">{pkg}</dt>
                <dd className="text-gray-900 font-mono">{version}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
