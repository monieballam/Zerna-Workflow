'use client';

import { useEffect, useMemo, useState } from 'react';
import { useFormState, useFormStatus } from 'react-dom';
import type { Dataset, DatasetVersionColumnsResponse, PipelineTemplate } from '@zerna/sdk';
import { createRunAction, resumeRunAction, type CreateRunState } from '@/lib/run-actions';
import {
  type ParameterSectionConfig,
  type RunFormAdvancedGroupConfig,
  type TemplateMethodEntry,
  DE_MODE_DETAIL_GUIDANCE,
  DE_MODE_SELECT_OPTIONS,
  METHOD_INFO,
  RUN_FORM_ADVANCED_GROUPS,
  RUN_FORM_BIOLOGY_FIRST_SECTION_IDS,
  RUN_FORM_MAIN_SECTIONS,
  formatFieldValue,
  buildLrCommunicationGroupingSelectOptions,
  getMethodName,
  getParameterFieldHelp,
  getParameterLabel,
  getRunFormManagedFieldNames,
  getSectionFields,
  filterMethodsForLaunchPreview,
  isFieldVisible,
  shouldOfferLineageSubclusterLrGrouping,
} from '@/lib/pipeline-parameter-presentation';
import {
  type LaunchPresetId,
  LAUNCH_PRESETS,
  applyLaunchPresetToParams,
  buildLargeRunAdvisory,
  estimateRunComplexity,
  getDatasetScaleSnapshot,
} from '@/lib/run-launch-heuristics';
import {
  applyConditionalParameterConstraints,
  buildRequiredParameterErrors,
  getConditionalForcedValues,
  getEffectiveRequiredFields,
  getParameterSchemaFromTemplate,
} from '@/lib/run-parameter-schema';

interface Props {
  templates: PipelineTemplate[];
  datasets: Dataset[];
  mode?: 'create' | 'resume';
  submitLabel?: string;
  resumeRunId?: string;
  initialTemplateId?: string;
  initialDatasetVersionId?: string;
  initialParameters?: Record<string, unknown>;
  lockTemplateSelection?: boolean;
  lockDatasetSelection?: boolean;
}

type SelectOption = {
  value: string;
  label: string;
};

const initialState: CreateRunState = {};
const DATASET_COLUMN_FIELDS = new Set([
  'batch_key',
  'hvg_batch_key',
  'cluster_key',
  'annotation_cluster_key',
]);
const LAST_USED_STORAGE_PREFIX = 'zerna.run-form.last-used.';
const RUN_FORM_MANAGED_FIELD_NAMES = new Set(getRunFormManagedFieldNames());

function runFormMainSectionFieldList(sectionId: string, fallback: string[]): string[] {
  return RUN_FORM_MAIN_SECTIONS.find((s) => s.id === sectionId)?.fields ?? fallback;
}

function runFormAdvancedGroupFieldList(groupId: string, fallback: string[]): string[] {
  return RUN_FORM_ADVANCED_GROUPS.find((g) => g.id === groupId)?.fields ?? fallback;
}

type StoredTemplateParameters = {
  updatedAt: string;
  parameters: Record<string, unknown>;
};

function resolveInitialTemplate(
  templates: PipelineTemplate[],
  initialTemplateId?: string
): PipelineTemplate | null {
  if (initialTemplateId) {
    return templates.find((t) => t.id === initialTemplateId) ?? null;
  }
  const visible = templates.filter((t) => t.visible_in_picker !== false);
  const pool = visible.length > 0 ? visible : templates;
  const rec = pool.find((t) => t.recommended);
  return rec ?? pool[0] ?? null;
}

function formatPipelineTemplateOptionLabel(template: PipelineTemplate): string {
  const base = `${template.name} v${template.version}`;
  if (template.recommended) return `${base} (recommended)`;
  return base;
}

function orderedUnique(values: string[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const value of values) {
    const cleaned = value.trim();
    if (!cleaned || seen.has(cleaned)) continue;
    seen.add(cleaned);
    ordered.push(cleaned);
  }
  return ordered;
}

function buildParameterDefaults(
  template: PipelineTemplate | null,
  initialValues?: Record<string, unknown>
): Record<string, unknown> {
  const properties = (
    template?.definition?.parameter_schema as {
      properties?: Record<string, Record<string, unknown>>;
    }
  )?.properties;
  const defaults: Record<string, unknown> = {};

  if (properties) {
    for (const [key, spec] of Object.entries(properties)) {
      if (spec?.default !== undefined) defaults[key] = spec.default;
    }
  }

  if (!initialValues) return defaults;

  for (const [key, value] of Object.entries(initialValues)) {
    if (key === 'progress') continue;
    defaults[key] = value;
  }

  return defaults;
}

function getTemplateStorageKey(templateId: string): string {
  return `${LAST_USED_STORAGE_PREFIX}${templateId}`;
}

function getStoredTemplateParameters(templateId: string): StoredTemplateParameters | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(getTemplateStorageKey(templateId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredTemplateParameters;
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      typeof parsed.updatedAt !== 'string' ||
      typeof parsed.parameters !== 'object' ||
      parsed.parameters === null ||
      Array.isArray(parsed.parameters)
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeStoredTemplateParameters(
  templateId: string,
  parameters: Record<string, unknown>
): StoredTemplateParameters | null {
  if (typeof window === 'undefined') return null;
  const payload: StoredTemplateParameters = {
    updatedAt: new Date().toISOString(),
    parameters: Object.fromEntries(
      Object.entries(parameters).filter(([, value]) => value !== undefined && value !== null)
    ),
  };
  window.localStorage.setItem(getTemplateStorageKey(templateId), JSON.stringify(payload));
  return payload;
}

function formatStoredTimestamp(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function mergeTemplateDefaultsWithStoredValues(
  template: PipelineTemplate | null,
  stored: StoredTemplateParameters | null
): Record<string, unknown> {
  const defaults = buildParameterDefaults(template);
  if (!stored) return defaults;
  return {
    ...defaults,
    ...stored.parameters,
  };
}

function resetFieldsToDefaults(
  currentValues: Record<string, unknown>,
  defaultValues: Record<string, unknown>,
  fields: string[]
): Record<string, unknown> {
  const next = { ...currentValues };
  for (const field of fields) {
    if (Object.prototype.hasOwnProperty.call(defaultValues, field)) {
      next[field] = defaultValues[field];
    } else {
      delete next[field];
    }
  }
  return next;
}

function getColumnSourceLabel(source: string | undefined): string {
  switch (source) {
    case 'metadata_file':
      return 'the uploaded metadata file';
    case 'h5ad_obs':
      return 'the uploaded H5AD obs table';
    case 'generated_only':
      return 'pipeline-generated defaults';
    default:
      return 'the selected dataset';
  }
}

function buildSelectableOptions(baseOptions: string[], currentValue: unknown): SelectOption[] {
  const current =
    typeof currentValue === 'string' && currentValue.trim().length > 0 ? currentValue.trim() : null;
  const options = orderedUnique(baseOptions);

  if (current && !options.includes(current)) {
    return [
      {
        value: current,
        label: `${current} (current value, not detected in this dataset)`,
      },
      ...options.map((value) => ({ value, label: value })),
    ];
  }

  return options.map((value) => ({ value, label: value }));
}

function preferredGeneratedClusterKey(values: Record<string, unknown>): string {
  return values.clustering_method === 'louvain' ? 'louvain' : 'leiden';
}

function isAllowedDatasetColumn(value: unknown, allowedColumns: string[]): value is string {
  if (typeof value !== 'string') return false;
  const cleaned = value.trim();
  return cleaned.length > 0 && allowedColumns.includes(cleaned);
}

function buildDatasetColumnErrors(
  columnInfo: DatasetVersionColumnsResponse | null,
  values: Record<string, unknown>
): Record<string, string> {
  if (!columnInfo) return {};

  const batchOptions = orderedUnique([...columnInfo.batch_candidates, ...columnInfo.obs_columns]);
  const clusterOptions = orderedUnique([
    ...columnInfo.cluster_candidates,
    ...columnInfo.obs_columns,
  ]);

  const errors: Record<string, string> = {};
  for (const fieldName of DATASET_COLUMN_FIELDS) {
    const rawValue = values[fieldName];
    if (typeof rawValue !== 'string' || rawValue.trim() === '') continue;
    const allowed = fieldName.includes('batch') ? batchOptions : clusterOptions;
    if (allowed.length === 0) continue;
    if (!allowed.includes(rawValue.trim())) {
      errors[fieldName] =
        `${getParameterLabel(fieldName)} must match an available column for the selected dataset version.`;
    }
  }

  return errors;
}

function SubmitButton({ disabled, label }: { disabled: boolean; label: string }) {
  const { pending } = useFormStatus();
  const pendingLabel = label.toLowerCase().includes('resume') ? 'Resuming…' : 'Creating…';
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}

function PipelineSteps({ methods }: { methods: TemplateMethodEntry[] }) {
  const [pipelineStepsOpen, setPipelineStepsOpen] = useState(true);
  return (
    <details
      open={pipelineStepsOpen}
      onToggle={(e) => setPipelineStepsOpen(e.currentTarget.open)}
      className="rounded-lg border border-gray-200 bg-gray-50 [&_summary]:list-none [&_summary::-webkit-details-marker]:hidden"
      data-testid="run-form-pipeline-steps"
    >
      <summary
        data-testid="run-form-pipeline-steps-summary"
        className="cursor-pointer select-none rounded-lg p-4 outline-none ring-blue-500 focus-visible:ring-2"
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Pipeline steps ({methods.length})
        </p>
      </summary>
      <ol
        className="space-y-2 border-t border-gray-200 px-4 pb-4 pt-3"
        data-testid="run-form-pipeline-steps-list"
      >
        {methods.map((entry, i) => {
          const methodName = getMethodName(entry);
          const info = METHOD_INFO[methodName];
          return (
            <li key={`${methodName}-${i}`} className="flex items-start gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-800">{info?.label ?? methodName}</p>
                {info?.description && (
                  <p className="mt-0.5 text-xs text-gray-500">{info.description}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function ParameterField({
  name,
  spec,
  value,
  onChange,
  className,
  required,
  error,
  selectOptions,
  selectHint,
  fieldHelp,
  locked,
  lockMessage,
}: {
  name: string;
  spec: Record<string, unknown>;
  value: unknown;
  onChange: (name: string, value: unknown) => void;
  className?: string;
  required?: boolean;
  error?: string;
  selectOptions?: SelectOption[];
  selectHint?: string;
  /** Run-form UX copy; when set, shown instead of the template schema description. */
  fieldHelp?: string;
  locked?: boolean;
  lockMessage?: string;
}) {
  const label = getParameterLabel(name);
  const type = spec.type as string | undefined;
  const min = spec.minimum as number | undefined;
  const max = spec.maximum as number | undefined;
  const enumValues = spec.enum as unknown[] | undefined;
  const defaultVal = spec.default;
  const schemaDescription =
    typeof spec.description === 'string' ? spec.description : 'No template description provided.';
  const description = fieldHelp ?? schemaDescription;

  const hint = [
    required ? 'required' : 'optional',
    type === 'integer' ? 'integer' : type === 'number' ? 'number' : null,
    min != null ? `min ${min}` : null,
    max != null ? `max ${max}` : null,
    defaultVal != null ? `default ${formatFieldValue(defaultVal)}` : 'no default',
  ]
    .filter(Boolean)
    .join(' · ');

  const id = `param-${name}`;
  const describedBy = [
    `${id}-description`,
    `${id}-hint`,
    locked ? `${id}-lock` : null,
    error ? `${id}-error` : null,
  ]
    .filter(Boolean)
    .join(' ');

  if (enumValues || (selectOptions && selectOptions.length > 0)) {
    const resolvedValue = value ?? defaultVal;
    const options =
      selectOptions && selectOptions.length > 0
        ? selectOptions
        : (enumValues ?? []).map((entry) => ({
            value: formatFieldValue(entry),
            label: formatFieldValue(entry),
          }));

    return (
      <div className={className}>
        <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
          <span>{label}</span>
          {required && (
            <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
              Required
            </span>
          )}
        </label>
        <select
          id={id}
          value={resolvedValue != null ? formatFieldValue(resolvedValue) : ''}
          onChange={(e) =>
            onChange(name, e.target.value || (defaultVal !== undefined ? defaultVal : undefined))
          }
          disabled={locked}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          className={`input w-full ${
            error ? 'border-red-300 focus:border-red-500 focus:ring-red-500' : ''
          }`}
        >
          {resolvedValue == null && <option value="">Select {label.toLowerCase()}…</option>}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p id={`${id}-description`} className="mt-1 text-xs text-gray-500">
          {description}
        </p>
        {selectHint && <p className="mt-1 text-xs text-blue-600">{selectHint}</p>}
        {locked && (
          <p id={`${id}-lock`} className="mt-1 text-xs font-medium text-indigo-700">
            {lockMessage ?? 'Locked by the current pipeline settings.'}
          </p>
        )}
        <p id={`${id}-hint`} className="mt-1 text-xs text-gray-400">
          {hint}
        </p>
        {error && (
          <p id={`${id}-error`} className="mt-1 text-xs font-medium text-red-600">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (type === 'boolean') {
    return (
      <div
        className={`rounded-lg border bg-white px-3 py-3 ${
          error ? 'border-red-300' : 'border-gray-200'
        } ${className ?? ''}`}
      >
        <div className="flex items-center gap-3">
          <input
            id={id}
            type="checkbox"
            checked={Boolean(value ?? defaultVal ?? false)}
            onChange={(e) => onChange(name, e.target.checked)}
            disabled={locked}
            aria-describedby={describedBy}
            aria-invalid={Boolean(error)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
          <label htmlFor={id} className="text-sm font-medium text-gray-700">
            {label}
          </label>
          {required && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
              Required
            </span>
          )}
        </div>
        <p id={`${id}-description`} className="mt-2 text-xs text-gray-500">
          {description}
        </p>
        {selectHint && <p className="mt-1 text-xs text-blue-600">{selectHint}</p>}
        {locked && (
          <p id={`${id}-lock`} className="mt-1 text-xs font-medium text-indigo-700">
            {lockMessage ?? 'Locked by the current pipeline settings.'}
          </p>
        )}
        <p id={`${id}-hint`} className="mt-1 text-xs text-gray-400">
          {hint}
        </p>
        {error && (
          <p id={`${id}-error`} className="mt-1 text-xs font-medium text-red-600">
            {error}
          </p>
        )}
      </div>
    );
  }

  const inputType = type === 'integer' || type === 'number' ? 'number' : 'text';
  const step = type === 'number' ? 'any' : '1';

  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
        <span>{label}</span>
        {required && (
          <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
            Required
          </span>
        )}
      </label>
      <input
        id={id}
        type={inputType}
        step={inputType === 'number' ? step : undefined}
        min={min}
        max={max}
        disabled={locked}
        value={value != null ? formatFieldValue(value) : ''}
        placeholder={defaultVal != null ? formatFieldValue(defaultVal) : undefined}
        aria-describedby={describedBy}
        aria-invalid={Boolean(error)}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') {
            onChange(name, defaultVal !== undefined ? defaultVal : undefined);
          } else if (type === 'integer') {
            onChange(name, parseInt(raw, 10));
          } else if (type === 'number') {
            onChange(name, parseFloat(raw));
          } else {
            onChange(name, raw);
          }
        }}
        className={`input w-full ${
          error ? 'border-red-300 focus:border-red-500 focus:ring-red-500' : ''
        }`}
      />
      <p id={`${id}-description`} className="mt-1 text-xs text-gray-500">
        {description}
      </p>
      {selectHint && <p className="mt-1 text-xs text-blue-600">{selectHint}</p>}
      {locked && (
        <p id={`${id}-lock`} className="mt-1 text-xs font-medium text-indigo-700">
          {lockMessage ?? 'Locked by the current pipeline settings.'}
        </p>
      )}
      <p id={`${id}-hint`} className="mt-1 text-xs text-gray-400">
        {hint}
      </p>
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

export default function RunCreateForm({
  templates,
  datasets,
  mode = 'create',
  submitLabel,
  resumeRunId,
  initialTemplateId,
  initialDatasetVersionId,
  initialParameters,
  lockTemplateSelection = false,
  lockDatasetSelection = false,
}: Props) {
  const initialResolved = resolveInitialTemplate(templates, initialTemplateId);
  const action = mode === 'resume' ? resumeRunAction : createRunAction;
  const [state, formAction] = useFormState(action, initialState);
  const [selectedTemplateId, setSelectedTemplateId] = useState(() => initialResolved?.id ?? '');
  const [selectedTemplate, setSelectedTemplate] = useState<PipelineTemplate | null>(
    () => initialResolved
  );
  const [selectedDatasetVersionId, setSelectedDatasetVersionId] = useState(
    initialDatasetVersionId ?? ''
  );
  const [paramValues, setParamValues] = useState<Record<string, unknown>>(() =>
    buildParameterDefaults(initialResolved, initialParameters)
  );
  const [datasetColumns, setDatasetColumns] = useState<DatasetVersionColumnsResponse | null>(null);
  const [datasetColumnError, setDatasetColumnError] = useState<string | null>(null);
  const [restoredFromLastUsed, setRestoredFromLastUsed] = useState(false);
  const [lastUsedUpdatedAt, setLastUsedUpdatedAt] = useState<string | null>(null);
  const [hasStoredTemplateValues, setHasStoredTemplateValues] = useState(false);
  const [launchPreset, setLaunchPreset] = useState<LaunchPresetId>('standard');

  const schema = useMemo(
    () => getParameterSchemaFromTemplate(selectedTemplate),
    [selectedTemplate]
  );
  const constrainedParamValues = useMemo(
    () => applyConditionalParameterConstraints(schema, paramValues),
    [paramValues, schema]
  );
  const forcedParameterValues = useMemo(
    () => getConditionalForcedValues(schema, constrainedParamValues),
    [constrainedParamValues, schema]
  );

  useEffect(() => {
    const raw = JSON.stringify(paramValues);
    const constrained = JSON.stringify(constrainedParamValues);
    if (raw === constrained) {
      return;
    }
    setParamValues(constrainedParamValues);
  }, [constrainedParamValues, paramValues]);

  function handleTemplateChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const nextTemplateId = event.target.value;
    const template = templates.find((entry) => entry.id === nextTemplateId) ?? null;
    setSelectedTemplateId(nextTemplateId);
    setSelectedTemplate(template);
    setLaunchPreset('standard');

    if (mode === 'create' && nextTemplateId) {
      const stored = getStoredTemplateParameters(nextTemplateId);
      setParamValues(mergeTemplateDefaultsWithStoredValues(template, stored));
      setRestoredFromLastUsed(Boolean(stored));
      setLastUsedUpdatedAt(stored?.updatedAt ?? null);
      setHasStoredTemplateValues(Boolean(stored));
      return;
    }

    setParamValues(buildParameterDefaults(template));
    setRestoredFromLastUsed(false);
    setLastUsedUpdatedAt(null);
    setHasStoredTemplateValues(false);
  }

  function handleDatasetChange(event: React.ChangeEvent<HTMLSelectElement>) {
    setSelectedDatasetVersionId(event.target.value);
  }

  function handleParamChange(name: string, value: unknown) {
    setParamValues((prev) => {
      const next = { ...prev, [name]: value };
      if (name === 'ambient_correction') {
        if (value === true) {
          const priorMethod =
            typeof prev.ambient_method === 'string' ? prev.ambient_method.trim().toLowerCase() : '';
          if (!priorMethod || priorMethod === 'off') {
            next.ambient_method = 'soupx';
          }
        }
        return next;
      }
      if (name !== 'clustering_method') return next;

      const desiredClusterKey = preferredGeneratedClusterKey(next);
      const priorClusterKey =
        typeof prev.cluster_key === 'string' ? prev.cluster_key.trim().toLowerCase() : '';
      const priorAnnotationClusterKey =
        typeof prev.annotation_cluster_key === 'string'
          ? prev.annotation_cluster_key.trim().toLowerCase()
          : '';

      if (!priorClusterKey || ['leiden', 'louvain'].includes(priorClusterKey)) {
        next.cluster_key = desiredClusterKey;
      }
      if (!priorAnnotationClusterKey || ['leiden', 'louvain'].includes(priorAnnotationClusterKey)) {
        next.annotation_cluster_key = desiredClusterKey;
      }

      return next;
    });
  }

  useEffect(() => {
    let cancelled = false;

    async function loadDatasetColumns() {
      if (!selectedDatasetVersionId) {
        setDatasetColumns(null);
        setDatasetColumnError(null);
        return;
      }

      try {
        setDatasetColumnError(null);
        const response = await fetch(
          `/api/proxy/v1/datasets/versions/${selectedDatasetVersionId}/columns`,
          { cache: 'no-store' }
        );
        if (!response.ok) {
          throw new Error(`Failed to load dataset columns (${response.status})`);
        }

        const payload = (await response.json()) as DatasetVersionColumnsResponse;
        if (cancelled) return;

        setDatasetColumns(payload);
        setParamValues((prev) => {
          const next = { ...prev };
          const batchOptions = orderedUnique([...payload.batch_candidates, ...payload.obs_columns]);
          const clusterOptions = orderedUnique([
            ...payload.cluster_candidates,
            ...payload.obs_columns,
          ]);
          const suggestedBatch = batchOptions[0];
          const desiredCluster = preferredGeneratedClusterKey(next);
          const suggestedCluster = clusterOptions.includes(desiredCluster)
            ? desiredCluster
            : clusterOptions[0];

          if (suggestedBatch && !isAllowedDatasetColumn(next.batch_key, batchOptions)) {
            next.batch_key = suggestedBatch;
          }
          if (suggestedBatch && !isAllowedDatasetColumn(next.hvg_batch_key, batchOptions)) {
            next.hvg_batch_key = suggestedBatch;
          }
          if (suggestedCluster && !isAllowedDatasetColumn(next.cluster_key, clusterOptions)) {
            next.cluster_key = suggestedCluster;
          }
          if (
            suggestedCluster &&
            !isAllowedDatasetColumn(next.annotation_cluster_key, clusterOptions)
          ) {
            next.annotation_cluster_key = suggestedCluster;
          }
          return next;
        });
      } catch (error) {
        if (cancelled) return;
        setDatasetColumns(null);
        setDatasetColumnError(
          error instanceof Error ? error.message : 'Failed to inspect dataset columns.'
        );
      }
    }

    void loadDatasetColumns();
    return () => {
      cancelled = true;
    };
  }, [selectedDatasetVersionId]);

  useEffect(() => {
    if (mode !== 'create') return;
    const tid = selectedTemplateId;
    const tmpl = selectedTemplate;
    if (!tid || !tmpl) return;
    const stored = getStoredTemplateParameters(tid);
    setHasStoredTemplateValues(Boolean(stored));
    if (stored) {
      setParamValues(mergeTemplateDefaultsWithStoredValues(tmpl, stored));
      setRestoredFromLastUsed(true);
      setLastUsedUpdatedAt(stored.updatedAt);
    }
    // Intentionally once on mount: default-recommended template may be pre-selected without a change event.
  }, []);

  const templateDefaultValues = useMemo(
    () => buildParameterDefaults(selectedTemplate),
    [selectedTemplate]
  );

  const scaleSnapshot = useMemo(
    () =>
      getDatasetScaleSnapshot(
        datasets,
        selectedDatasetVersionId,
        datasetColumns ? datasetColumns.batch_candidates.length : null
      ),
    [datasets, selectedDatasetVersionId, datasetColumns]
  );

  const batchCandidateCount = datasetColumns?.batch_candidates.length ?? null;

  const runComplexityEstimate = useMemo(() => {
    if (!scaleSnapshot) return null;
    const cells = scaleSnapshot.cellCount;
    const genes = scaleSnapshot.geneCount;
    const batchOn = constrainedParamValues.batch_correction === true;
    const integrationMode = String(
      constrainedParamValues.integration_mode ?? 'harmony'
    ).toLowerCase();
    const scvi = integrationMode === 'scvi' || constrainedParamValues.batch_method === 'scvi';
    const pathway = constrainedParamValues.pathway_scoring === true;
    const lr = constrainedParamValues.ligand_receptor === true;
    const deMode = String(constrainedParamValues.de_mode ?? '').toLowerCase();
    const pseudobulkish =
      deMode === 'pseudobulk_sample_level_contrast' || deMode === 'condition_de_within_celltype';
    let heavyOptionalCount = 0;
    if (pathway) heavyOptionalCount += 1;
    if (lr) heavyOptionalCount += 1;
    if (pseudobulkish) heavyOptionalCount += 1;
    return estimateRunComplexity(cells, genes, constrainedParamValues, {
      batchCorrectionEnabled: batchOn,
      scvi,
      heavyOptionalCount,
    });
  }, [scaleSnapshot, constrainedParamValues]);

  const runComplexityLabel =
    runComplexityEstimate === 'very_heavy'
      ? 'Very heavy'
      : runComplexityEstimate === 'heavy'
        ? 'Heavy'
        : 'Standard';

  const largeRunAdvisory = useMemo(
    () => buildLargeRunAdvisory(scaleSnapshot, constrainedParamValues, batchCandidateCount),
    [scaleSnapshot, constrainedParamValues, batchCandidateCount]
  );

  function handleLaunchPresetChange(next: LaunchPresetId) {
    setLaunchPreset(next);
    setParamValues((prev) =>
      applyLaunchPresetToParams(
        next,
        prev,
        templateDefaultValues,
        schema?.properties as Record<string, Record<string, unknown>> | undefined
      )
    );
  }

  const methods = (selectedTemplate?.definition?.methods ?? []) as TemplateMethodEntry[];
  const selectedMethodNames = useMemo(
    () => new Set(methods.map((entry) => getMethodName(entry)).filter(Boolean)),
    [methods]
  );

  const { mainSections, advancedGroups, additionalFields } = useMemo(() => {
    const properties = schema?.properties ?? {};

    const mainSectionsRaw = RUN_FORM_MAIN_SECTIONS.map((section) => {
      const fields = getSectionFields(
        section,
        properties,
        selectedMethodNames,
        constrainedParamValues
      );
      if (fields.length === 0) return null;
      return { ...section, fields };
    }).filter((section): section is ParameterSectionConfig & { fields: string[] } =>
      Boolean(section)
    );

    const mainFieldOwner = new Map<string, number>();
    mainSectionsRaw.forEach((section, idx) => {
      for (const name of section.fields) {
        mainFieldOwner.set(name, idx);
      }
    });
    const mainSections = mainSectionsRaw
      .map((section, idx) => {
        const fields = section.fields.filter((name) => mainFieldOwner.get(name) === idx);
        if (fields.length === 0) return null;
        return { ...section, fields };
      })
      .filter((section): section is ParameterSectionConfig & { fields: string[] } =>
        Boolean(section)
      );

    const advancedGroups = RUN_FORM_ADVANCED_GROUPS.map((group) => {
      const fields = getSectionFields(
        group,
        properties,
        selectedMethodNames,
        constrainedParamValues
      );
      if (fields.length === 0) return null;
      return { ...group, fields };
    }).filter((group): group is RunFormAdvancedGroupConfig & { fields: string[] } =>
      Boolean(group)
    );

    const additionalFields = Object.keys(properties).filter(
      (fieldName) =>
        !RUN_FORM_MANAGED_FIELD_NAMES.has(fieldName) &&
        isFieldVisible(fieldName, constrainedParamValues)
    );

    return { mainSections, advancedGroups, additionalFields };
  }, [constrainedParamValues, schema?.properties, selectedMethodNames]);

  const showStandaloneRandomSeed = Boolean(schema?.properties && !schema.properties.random_seed);
  const showAdvancedRegion =
    advancedGroups.length > 0 || additionalFields.length > 0 || showStandaloneRandomSeed;
  const hasRunParameterUi =
    Boolean(schema?.properties && Object.keys(schema.properties).length > 0) &&
    (mainSections.length > 0 || showAdvancedRegion);

  const requiredFields = useMemo(
    () => getEffectiveRequiredFields(schema, constrainedParamValues),
    [constrainedParamValues, schema]
  );

  const clientParameterErrors = useMemo(
    () => buildRequiredParameterErrors(schema, constrainedParamValues),
    [constrainedParamValues, schema]
  );

  const datasetColumnErrors = useMemo(
    () => buildDatasetColumnErrors(datasetColumns, constrainedParamValues),
    [datasetColumns, constrainedParamValues]
  );

  const columnSelectOptions = useMemo(() => {
    if (!datasetColumns) return {} as Partial<Record<string, SelectOption[]>>;
    return {
      batch_key: buildSelectableOptions(
        [...datasetColumns.batch_candidates, ...datasetColumns.obs_columns],
        constrainedParamValues.batch_key
      ),
      hvg_batch_key: buildSelectableOptions(
        [...datasetColumns.batch_candidates, ...datasetColumns.obs_columns],
        constrainedParamValues.hvg_batch_key
      ),
      cluster_key: buildSelectableOptions(
        [...datasetColumns.cluster_candidates, ...datasetColumns.obs_columns],
        constrainedParamValues.cluster_key
      ),
      annotation_cluster_key: buildSelectableOptions(
        [...datasetColumns.cluster_candidates, ...datasetColumns.obs_columns],
        constrainedParamValues.annotation_cluster_key
      ),
    };
  }, [datasetColumns, constrainedParamValues]);

  const launchPreviewMethodNames = useMemo(
    () =>
      filterMethodsForLaunchPreview(methods, constrainedParamValues).map((e) => getMethodName(e)),
    [methods, constrainedParamValues]
  );

  const showLineageSubclusterLrOption = useMemo(
    () =>
      shouldOfferLineageSubclusterLrGrouping({
        datasetObsColumns: datasetColumns?.obs_columns,
        launchPreviewMethodNames,
      }),
    [datasetColumns?.obs_columns, launchPreviewMethodNames]
  );

  const lrCommunicationGroupingSelectOptions = useMemo(() => {
    const raw = schema?.properties?.lr_communication_grouping;
    const enumValues =
      raw && typeof raw === 'object' && Array.isArray((raw as { enum?: unknown[] }).enum)
        ? (raw as { enum: unknown[] }).enum
        : undefined;
    return buildLrCommunicationGroupingSelectOptions({
      schemaEnum: enumValues,
      showLineageSubcluster: showLineageSubclusterLrOption,
    });
  }, [schema, showLineageSubclusterLrOption]);

  const visibleForcedParameterEntries = useMemo(
    () =>
      Object.entries(forcedParameterValues).filter(([fieldName]) =>
        isFieldVisible(fieldName, constrainedParamValues)
      ),
    [forcedParameterValues, constrainedParamValues]
  );

  useEffect(() => {
    if (constrainedParamValues.lr_communication_grouping !== 'lineage_subcluster') return;
    if (showLineageSubclusterLrOption) return;
    setParamValues((prev) =>
      prev.lr_communication_grouping === 'lineage_subcluster'
        ? { ...prev, lr_communication_grouping: 'auto' }
        : prev
    );
  }, [showLineageSubclusterLrOption, constrainedParamValues.lr_communication_grouping]);

  function resolveParameterSelectProps(fieldName: string): {
    selectOptions: SelectOption[] | undefined;
    selectHint: string | undefined;
  } {
    const columnOpts = columnSelectOptions[fieldName as keyof typeof columnSelectOptions];
    if (fieldName === 'de_mode') {
      return { selectOptions: DE_MODE_SELECT_OPTIONS, selectHint: undefined };
    }
    if (fieldName === 'lr_communication_grouping') {
      return {
        selectOptions: lrCommunicationGroupingSelectOptions,
        selectHint: showLineageSubclusterLrOption
          ? 'Advanced / exploratory: LIANA groupby uses P2 lineage_subcluster partitions (technical IDs preserved in results). Default auto still prefers canonical CCI tiers. Small partitions are excluded by min cells per group.'
          : undefined,
      };
    }
    return {
      selectOptions: columnOpts,
      selectHint: columnOpts ? columnSelectHint : undefined,
    };
  }

  const submitDisabled =
    !selectedTemplate ||
    !selectedDatasetVersionId ||
    Object.keys(clientParameterErrors).length > 0 ||
    Object.keys(datasetColumnErrors).length > 0;

  const parametersJson = JSON.stringify(
    Object.fromEntries(
      Object.entries(constrainedParamValues).filter(([, value]) => value !== undefined)
    )
  );
  const submitButtonLabel = submitLabel ?? (mode === 'resume' ? 'Resume run' : 'Create run');
  const columnSelectHint = datasetColumns
    ? `Options inferred from ${getColumnSourceLabel(datasetColumns.source)}.`
    : undefined;
  const lastUsedLabel = formatStoredTimestamp(lastUsedUpdatedAt);

  function handleResetAllDefaults() {
    if (!selectedTemplate) return;
    setParamValues(templateDefaultValues);
    setRestoredFromLastUsed(false);
    setLaunchPreset('standard');
  }

  function handleRestoreLastUsed() {
    if (mode !== 'create' || !selectedTemplateId || !selectedTemplate) return;
    const stored = getStoredTemplateParameters(selectedTemplateId);
    if (!stored) return;
    setParamValues(mergeTemplateDefaultsWithStoredValues(selectedTemplate, stored));
    setRestoredFromLastUsed(true);
    setLastUsedUpdatedAt(stored.updatedAt);
    setHasStoredTemplateValues(true);
  }

  function handleFormSubmit() {
    if (mode !== 'create' || !selectedTemplateId || submitDisabled) return;
    const stored = writeStoredTemplateParameters(selectedTemplateId, constrainedParamValues);
    if (!stored) return;
    setHasStoredTemplateValues(true);
    setLastUsedUpdatedAt(stored.updatedAt);
  }

  return (
    <form action={formAction} onSubmit={handleFormSubmit} className="max-w-5xl space-y-6">
      {mode === 'resume' && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          This will reuse the failed run and continue from its saved checkpoint. Dataset and
          template are locked so the existing completed steps remain valid.
        </div>
      )}

      {state.error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {state.error}
        </div>
      )}

      <input type="hidden" name="dataset_version_id" value={selectedDatasetVersionId} />
      <input type="hidden" name="template_id" value={selectedTemplateId} />
      {mode === 'resume' && resumeRunId && (
        <input type="hidden" name="run_id" value={resumeRunId} />
      )}

      <div>
        <label
          htmlFor="dataset_version_id"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Dataset version
        </label>
        <select
          id="dataset_version_id"
          required
          value={selectedDatasetVersionId}
          onChange={handleDatasetChange}
          disabled={lockDatasetSelection}
          className="input w-full"
          aria-describedby={state.fieldErrors?.dataset_version_id ? 'dv-error' : undefined}
        >
          <option value="">Select a dataset version…</option>
          {datasets.flatMap((dataset) =>
            dataset.versions.map((version) => (
              <option key={version.id} value={version.id}>
                {dataset.name} — {version.version}
                {version.cell_count != null
                  ? ` (${version.cell_count.toLocaleString()} cells)`
                  : ''}
              </option>
            ))
          )}
        </select>
        {state.fieldErrors?.dataset_version_id && (
          <p id="dv-error" className="mt-1 text-xs text-red-600">
            {state.fieldErrors.dataset_version_id}
          </p>
        )}
        {!state.fieldErrors?.dataset_version_id && datasetColumnError && (
          <p className="mt-1 text-xs text-amber-700">{datasetColumnError}</p>
        )}
      </div>

      {scaleSnapshot && (
        <div
          data-testid="dataset-scale-summary"
          className="rounded-lg border border-gray-200 bg-slate-50/80 p-4 text-sm text-gray-800"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Dataset scale
          </p>
          <p className="mt-1 font-medium text-gray-900">
            {scaleSnapshot.datasetName} — v{scaleSnapshot.versionLabel}
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs text-gray-700">
            <div>
              <dt className="text-gray-500">Cells (ingest estimate)</dt>
              <dd className="font-semibold text-gray-900">
                {scaleSnapshot.cellCount != null
                  ? scaleSnapshot.cellCount.toLocaleString()
                  : 'Unknown'}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Genes (ingest estimate)</dt>
              <dd className="font-semibold text-gray-900">
                {scaleSnapshot.geneCount != null
                  ? scaleSnapshot.geneCount.toLocaleString()
                  : 'Unknown'}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Batch-like columns detected</dt>
              <dd className="font-semibold text-gray-900">
                {scaleSnapshot.batchLikeColumnCount != null
                  ? scaleSnapshot.batchLikeColumnCount.toLocaleString()
                  : selectedDatasetVersionId
                    ? '—'
                    : 'Select a dataset'}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Inputs / merge</dt>
              <dd className="font-semibold text-gray-900">
                {scaleSnapshot.mergeOrSourceHint ?? 'No merge hint in metadata'}
              </dd>
            </div>
          </dl>
          {runComplexityEstimate && (
            <p className="mt-3 text-xs text-gray-600" data-testid="run-complexity-estimate">
              Estimated run load:{' '}
              <span className="font-semibold text-gray-900">{runComplexityLabel}</span> — heuristic
              from size and current toggles (guidance only; does not block launch).
            </p>
          )}
        </div>
      )}

      <div>
        <label htmlFor="template_id" className="mb-1 block text-sm font-medium text-gray-700">
          Pipeline template
        </label>
        <select
          id="template_id"
          required
          value={selectedTemplateId}
          className="input w-full"
          onChange={handleTemplateChange}
          disabled={lockTemplateSelection}
          aria-describedby={state.fieldErrors?.template_id ? 'tmpl-error' : undefined}
        >
          <option value="">Select a pipeline…</option>
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {formatPipelineTemplateOptionLabel(template)}
            </option>
          ))}
        </select>
        {selectedTemplate &&
          (() => {
            const raw = (
              selectedTemplate.definition?.metadata as Record<string, unknown> | undefined
            )?.description;
            const text = typeof raw === 'string' ? raw.trim() : '';
            return text ? (
              <p className="mt-1 text-xs text-gray-600" id="template_id-description">
                {text}
              </p>
            ) : null;
          })()}
        {state.fieldErrors?.template_id && (
          <p id="tmpl-error" className="mt-1 text-xs text-red-600">
            {state.fieldErrors.template_id}
          </p>
        )}
      </div>

      {largeRunAdvisory && (
        <div
          role="status"
          data-testid="large-run-advisory"
          className={`rounded-lg border p-4 text-sm ${
            largeRunAdvisory.complexity === 'very_heavy'
              ? 'border-red-200 bg-red-50 text-red-950'
              : 'border-amber-200 bg-amber-50 text-amber-950'
          }`}
        >
          <p className="font-semibold">Memory and scale advisory</p>
          <p className="mt-1 text-xs opacity-90">
            This run may require substantial memory. Large merged runs are more likely to fail
            during normalization, PCA, or integration. The checks below are guidance only — they do
            not block launch.
          </p>
          <p className="mt-2 text-xs font-medium uppercase tracking-wide opacity-80">
            Estimated load: {largeRunAdvisory.complexityLabel}
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
            {largeRunAdvisory.riskSignals.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs font-semibold">What you can do</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
            {largeRunAdvisory.suggestions.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {methods.length > 0 && (
        <PipelineSteps methods={filterMethodsForLaunchPreview(methods, constrainedParamValues)} />
      )}

      {hasRunParameterUi && (
        <fieldset className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <legend className="text-sm font-semibold text-gray-700">Run parameters</legend>
              <p className="-mt-2 text-xs text-gray-500">
                <span className="font-medium text-gray-700">Biology-first sections</span> (batch,
                annotation, DE, optional analyses) are highlighted. QC and clustering use standard
                defaults; expert tuning stays under Advanced settings. Required fields must be set
                before launch.
              </p>
            </div>
            {mode === 'create' && selectedTemplate && (
              <div className="flex shrink-0 flex-wrap gap-2">
                {selectedTemplateId && hasStoredTemplateValues && (
                  <button
                    type="button"
                    onClick={handleRestoreLastUsed}
                    className="rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Use last run values
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleResetAllDefaults}
                  className="rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                >
                  Restore all defaults
                </button>
              </div>
            )}
          </div>
          {mode === 'create' && restoredFromLastUsed && (
            <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
              Restored your last-used parameters for this template
              {lastUsedLabel ? ` from ${lastUsedLabel}` : ''}. You can reset any section or the
              entire form back to template defaults.
            </div>
          )}
          {state.fieldErrors?.parameters && (
            <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {state.fieldErrors.parameters}
            </div>
          )}
          {Object.keys(clientParameterErrors).length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Complete the required parameters highlighted below before starting the run.
            </div>
          )}
          {Object.keys(datasetColumnErrors).length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Correct the dataset-column selections highlighted below before starting the run.
            </div>
          )}
          {visibleForcedParameterEntries.length > 0 && (
            <div className="rounded-md border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
              <p className="font-medium">
                Some parameters were fixed automatically to keep this run configuration valid.
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-indigo-900/90">
                {visibleForcedParameterEntries.map(([fieldName, constraint]) => (
                  <li key={fieldName}>
                    {getParameterLabel(fieldName)} = {formatFieldValue(constraint.value)}
                    {constraint.reason ? ` — ${constraint.reason}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {mode === 'create' && selectedTemplate && (
            <div
              className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4"
              data-testid="launch-preset-selector"
            >
              <label htmlFor="launch_preset" className="block text-sm font-semibold text-gray-900">
                Launch preset
              </label>
              <p className="mt-1 text-xs text-gray-600">
                Applies a bundle of recommended toggles. You can change any field afterward —
                presets are shortcuts, not locked modes.
              </p>
              <select
                id="launch_preset"
                className="input mt-2 max-w-md"
                value={launchPreset}
                onChange={(e) => handleLaunchPresetChange(e.target.value as LaunchPresetId)}
              >
                {LAUNCH_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} — {p.shortDescription}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-xs text-gray-600">
                {LAUNCH_PRESETS.find((p) => p.id === launchPreset)?.detail}
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {mainSections.map((section) => {
              const collapsible = section.defaultExpanded === false;
              const compact = collapsible && section.fields.length === 1;
              const shellPad = compact ? 'p-3' : 'p-5';
              const fieldGridClass = compact ? 'gap-3' : 'gap-4';
              const biologyFirst = RUN_FORM_BIOLOGY_FIRST_SECTION_IDS.has(section.id);
              const biologyShell =
                'rounded-xl border bg-gray-50 [&_summary]:list-none [&_summary::-webkit-details-marker]:hidden ';
              const biologyRing = biologyFirst
                ? 'border-amber-300/90 ring-1 ring-amber-200/80 '
                : 'border-gray-200 ';

              const headerRow = (
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">{section.title}</h3>
                    <p className="mt-1 text-xs text-gray-500">{section.description}</p>
                  </div>
                  {mode === 'create' && (
                    <button
                      type="button"
                      onClick={() =>
                        setParamValues((prev) =>
                          resetFieldsToDefaults(
                            prev,
                            templateDefaultValues,
                            runFormMainSectionFieldList(section.id, section.fields)
                          )
                        )
                      }
                      className="shrink-0 rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Restore step defaults
                    </button>
                  )}
                </div>
              );

              const fieldsGrid = (
                <div className={`grid grid-cols-1 md:grid-cols-2 ${fieldGridClass}`}>
                  {section.fields.map((name) => {
                    const spec = schema?.properties?.[name];
                    if (!spec) return null;

                    const isBoolean = spec.type === 'boolean';
                    const { selectOptions, selectHint } = resolveParameterSelectProps(name);
                    return (
                      <ParameterField
                        key={name}
                        name={name}
                        spec={spec}
                        value={constrainedParamValues[name]}
                        onChange={handleParamChange}
                        required={requiredFields.has(name)}
                        locked={Boolean(forcedParameterValues[name])}
                        lockMessage={forcedParameterValues[name]?.reason}
                        error={
                          clientParameterErrors[name] ??
                          datasetColumnErrors[name] ??
                          state.fieldErrors?.[name]
                        }
                        selectOptions={selectOptions}
                        selectHint={selectHint}
                        fieldHelp={getParameterFieldHelp(name)}
                        className={isBoolean ? 'md:col-span-2' : undefined}
                      />
                    );
                  })}
                </div>
              );

              const deGuidance =
                section.id === 'de_main' && typeof constrainedParamValues.de_mode === 'string'
                  ? DE_MODE_DETAIL_GUIDANCE[constrainedParamValues.de_mode]
                  : null;

              const guidanceBlock =
                deGuidance != null ? (
                  <div
                    className="mt-4 rounded-lg border border-sky-200 bg-sky-50/90 p-3 text-xs text-sky-950"
                    data-testid="de-mode-guidance"
                  >
                    <p className="font-semibold text-sky-900">{deGuidance.headline}</p>
                    <p className="mt-1 text-sky-900/95">{deGuidance.body}</p>
                    {deGuidance.keys ? (
                      <p className="mt-2 text-sky-900/85">
                        <span className="font-medium">Keys:</span> {deGuidance.keys}
                      </p>
                    ) : null}
                  </div>
                ) : null;

              if (collapsible) {
                return (
                  <section
                    key={section.id}
                    data-testid={`run-form-main-section-${section.id}`}
                    className={`${biologyShell}${biologyRing}${
                      section.fullWidth ? 'lg:col-span-2' : ''
                    }`}
                  >
                    <details className="group">
                      <summary className="cursor-pointer select-none rounded-xl outline-none ring-blue-500 focus-visible:ring-2">
                        <div className={shellPad}>{headerRow}</div>
                      </summary>
                      <div
                        className={`border-t border-gray-200 px-5 pb-5 pt-4 ${compact ? '!px-3 !pb-3 !pt-3' : ''}`}
                      >
                        {fieldsGrid}
                        {guidanceBlock}
                      </div>
                    </details>
                  </section>
                );
              }

              return (
                <section
                  key={section.id}
                  data-testid={`run-form-main-section-${section.id}`}
                  className={`${biologyShell}${biologyRing}p-5 ${
                    section.fullWidth ? 'lg:col-span-2' : ''
                  }`}
                >
                  <div className="mb-4">{headerRow}</div>
                  {fieldsGrid}
                  {guidanceBlock}
                </section>
              );
            })}
          </div>

          {showAdvancedRegion && (
            <details
              data-testid="run-form-advanced"
              className="rounded-xl border border-gray-200 bg-gray-50 [&_summary]:list-none [&_summary::-webkit-details-marker]:hidden"
            >
              <summary
                data-testid="run-form-advanced-summary"
                className="cursor-pointer select-none rounded-xl p-5 outline-none ring-blue-500 focus-visible:ring-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span className="text-sm font-semibold text-gray-900">Advanced settings</span>
                    <p className="mt-1 text-xs text-gray-500">
                      Advanced settings for expert tuning. Most runs do not need changes here.
                    </p>
                  </div>
                </div>
              </summary>
              <div className="space-y-4 border-t border-gray-200 px-5 pb-5 pt-4">
                {advancedGroups.map((group) => (
                  <section
                    key={group.id}
                    className="rounded-lg border border-gray-200 bg-white/60 p-4 shadow-sm"
                  >
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-700">
                          {group.title}
                        </h4>
                        {'description' in group && group.description ? (
                          <p className="mt-1 text-xs text-gray-500">{group.description}</p>
                        ) : null}
                      </div>
                      {mode === 'create' && (
                        <button
                          type="button"
                          onClick={() =>
                            setParamValues((prev) =>
                              resetFieldsToDefaults(
                                prev,
                                templateDefaultValues,
                                runFormAdvancedGroupFieldList(group.id, group.fields)
                              )
                            )
                          }
                          className="shrink-0 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          Restore subsection defaults
                        </button>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      {group.fields.map((name) => {
                        const spec = schema?.properties?.[name];
                        if (!spec) return null;
                        const isBoolean = spec.type === 'boolean';
                        const { selectOptions, selectHint } = resolveParameterSelectProps(name);
                        return (
                          <ParameterField
                            key={name}
                            name={name}
                            spec={spec}
                            value={constrainedParamValues[name]}
                            onChange={handleParamChange}
                            required={requiredFields.has(name)}
                            locked={Boolean(forcedParameterValues[name])}
                            lockMessage={forcedParameterValues[name]?.reason}
                            error={
                              clientParameterErrors[name] ??
                              datasetColumnErrors[name] ??
                              state.fieldErrors?.[name]
                            }
                            selectOptions={selectOptions}
                            selectHint={selectHint}
                            fieldHelp={getParameterFieldHelp(name)}
                            className={isBoolean ? 'md:col-span-2' : undefined}
                          />
                        );
                      })}
                    </div>
                  </section>
                ))}

                {additionalFields.length > 0 && (
                  <section className="rounded-lg border border-gray-200 bg-white/60 p-4 shadow-sm">
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div>
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-700">
                          Additional template parameters
                        </h4>
                        <p className="mt-1 text-xs text-gray-500">
                          Extra fields from this template that are not part of the standard layout.
                        </p>
                      </div>
                      {mode === 'create' && (
                        <button
                          type="button"
                          onClick={() =>
                            setParamValues((prev) =>
                              resetFieldsToDefaults(prev, templateDefaultValues, additionalFields)
                            )
                          }
                          className="shrink-0 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          Restore subsection defaults
                        </button>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      {additionalFields.map((name) => {
                        const spec = schema?.properties?.[name];
                        if (!spec) return null;
                        const isBoolean = spec.type === 'boolean';
                        const { selectOptions, selectHint } = resolveParameterSelectProps(name);
                        return (
                          <ParameterField
                            key={name}
                            name={name}
                            spec={spec}
                            value={constrainedParamValues[name]}
                            onChange={handleParamChange}
                            required={requiredFields.has(name)}
                            locked={Boolean(forcedParameterValues[name])}
                            lockMessage={forcedParameterValues[name]?.reason}
                            error={
                              clientParameterErrors[name] ??
                              datasetColumnErrors[name] ??
                              state.fieldErrors?.[name]
                            }
                            selectOptions={selectOptions}
                            selectHint={selectHint}
                            fieldHelp={getParameterFieldHelp(name)}
                            className={isBoolean ? 'md:col-span-2' : undefined}
                          />
                        );
                      })}
                    </div>
                  </section>
                )}

                {showStandaloneRandomSeed && (
                  <div className="rounded-lg border border-gray-200 bg-white/60 p-4 shadow-sm">
                    <label
                      htmlFor="random_seed"
                      className="mb-1 block text-sm font-medium text-gray-700"
                    >
                      Random seed <span className="font-normal text-gray-400">(optional)</span>
                    </label>
                    <input
                      id="random_seed"
                      name="random_seed"
                      type="number"
                      min={0}
                      placeholder="e.g. 42"
                      className="input w-40"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      Set for reproducible results across runs.
                    </p>
                  </div>
                )}
              </div>
            </details>
          )}
        </fieldset>
      )}

      <input type="hidden" name="parameters" value={parametersJson} />

      <div className="flex gap-3 pt-2">
        <SubmitButton disabled={submitDisabled} label={submitButtonLabel} />
        <a href="/runs" className="btn-secondary">
          Cancel
        </a>
      </div>
    </form>
  );
}
