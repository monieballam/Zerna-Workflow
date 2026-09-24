'use client';

import { useMemo, useState } from 'react';
import { useFormState, useFormStatus } from 'react-dom';
import type { PipelineMethodCatalogEntry, PipelineTemplate } from '@zerna/sdk';
import { savePipelineTemplateAction, type SavePipelineTemplateState } from '@/lib/pipeline-actions';

type MethodEntry = string | { name?: string; enabled_if?: string | string[] | boolean };
type ParameterType = 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object';

interface ParameterFieldRow {
  id: string;
  name: string;
  type: ParameterType;
  description: string;
  defaultValue: string;
  minimum: string;
  maximum: string;
  enumValues: string;
  required: boolean;
}

interface Props {
  catalog: PipelineMethodCatalogEntry[];
  initialTemplate?: PipelineTemplate | null;
}

const initialState: SavePipelineTemplateState = {};
const PARAMETER_TYPES: ParameterType[] = [
  'string',
  'number',
  'integer',
  'boolean',
  'array',
  'object',
];

function generateId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function getMethodName(entry: MethodEntry): string {
  return typeof entry === 'string' ? entry : String(entry.name ?? '');
}

function parseMethodSelection(
  catalog: PipelineMethodCatalogEntry[],
  template?: PipelineTemplate | null
): string[] {
  const methods = (template?.definition?.methods ?? []) as MethodEntry[];
  if (methods.length > 0) {
    return methods.map(getMethodName).filter(Boolean);
  }

  return [...catalog]
    .sort((a, b) => a.order - b.order)
    .filter((entry) => entry.default_selected)
    .map((entry) => entry.name);
}

function stringifyValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function stringifyScalar(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

function parseParameterRows(template?: PipelineTemplate | null): ParameterFieldRow[] {
  const definition = template?.definition ?? {};
  const parameterSchema = (definition.parameter_schema as
    | { properties?: Record<string, Record<string, unknown>>; required?: string[] }
    | undefined) ?? { properties: {}, required: [] };

  const required = new Set(parameterSchema.required ?? []);
  const rows = Object.entries(parameterSchema.properties ?? {}).map(([name, spec]) => ({
    id: generateId(),
    name,
    type: (spec.type as ParameterType | undefined) ?? 'string',
    description: typeof spec.description === 'string' ? spec.description : '',
    defaultValue: stringifyValue(spec.default),
    minimum: stringifyScalar(spec.minimum),
    maximum: stringifyScalar(spec.maximum),
    enumValues: Array.isArray(spec.enum)
      ? spec.enum.map((value) => stringifyValue(value)).join(', ')
      : '',
    required: required.has(name),
  }));

  return rows.length > 0
    ? rows
    : [
        {
          id: generateId(),
          name: 'random_seed',
          type: 'integer',
          description: 'Global random seed for reproducibility.',
          defaultValue: '42',
          minimum: '0',
          maximum: '',
          enumValues: '',
          required: false,
        },
      ];
}

function parseTypedValue(raw: string, type: ParameterType): unknown {
  const value = raw.trim();
  if (value === '') return undefined;

  if (type === 'integer') {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) throw new Error(`Invalid integer value: ${raw}`);
    return parsed;
  }

  if (type === 'number') {
    const parsed = Number.parseFloat(value);
    if (Number.isNaN(parsed)) throw new Error(`Invalid number value: ${raw}`);
    return parsed;
  }

  if (type === 'boolean') {
    if (value === 'true') return true;
    if (value === 'false') return false;
    throw new Error(`Boolean values must be 'true' or 'false': ${raw}`);
  }

  if (type === 'array' || type === 'object') {
    return JSON.parse(value);
  }

  return value;
}

function parseEnumValues(raw: string, type: ParameterType): unknown[] | undefined {
  const value = raw.trim();
  if (!value) return undefined;

  if (type === 'array' || type === 'object') {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      throw new Error('Enum values for array/object types must be a JSON array.');
    }
    const parsedArray: unknown[] = parsed;
    return parsedArray;
  }

  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => parseTypedValue(item, type));
}

function buildParameterSchema(rows: ParameterFieldRow[]): Record<string, unknown> {
  const properties: Record<string, Record<string, unknown>> = {};
  const required: string[] = [];
  const names = new Set<string>();

  for (const row of rows) {
    const name = row.name.trim();
    if (!name) continue;

    if (names.has(name)) {
      throw new Error(`Duplicate parameter name: ${name}`);
    }
    names.add(name);

    const spec: Record<string, unknown> = {
      type: row.type,
    };
    if (row.description.trim()) spec.description = row.description.trim();

    const defaultValue = parseTypedValue(row.defaultValue, row.type);
    if (defaultValue !== undefined) spec.default = defaultValue;

    if ((row.type === 'number' || row.type === 'integer') && row.minimum.trim()) {
      spec.minimum = parseTypedValue(row.minimum, row.type);
    }
    if ((row.type === 'number' || row.type === 'integer') && row.maximum.trim()) {
      spec.maximum = parseTypedValue(row.maximum, row.type);
    }

    const enumValues = parseEnumValues(row.enumValues, row.type);
    if (enumValues && enumValues.length > 0) spec.enum = enumValues;

    properties[name] = spec;
    if (row.required) required.push(name);
  }

  const allOf: Record<string, unknown>[] = [];
  if (properties.batch_correction && properties.batch_key) {
    allOf.push({
      if: { properties: { batch_correction: { const: true } } },
      then: { required: ['batch_key'] },
    });
  }
  if (properties.pathway_scoring && properties.pathway_net_path) {
    allOf.push({
      if: { properties: { pathway_scoring: { const: true } } },
      then: { required: ['pathway_net_path'] },
    });
  }

  return {
    type: 'object',
    properties,
    required,
    ...(allOf.length > 0 ? { allOf } : {}),
  };
}

function buildDependencies(methods: MethodEntry[]): Record<string, string[]> {
  const methodNames = methods.map(getMethodName).filter(Boolean);
  const selected = new Set(methodNames);
  const dependencies: Record<string, string[]> = {};

  function add(step: string, dependency: string) {
    if (!selected.has(step) || !selected.has(dependency)) return;
    dependencies[step] ??= [];
    if (!dependencies[step].includes(dependency)) {
      dependencies[step].push(dependency);
    }
  }

  if (selected.has('doublet_detection')) add('doublet_detection', 'qc_filter');

  if (selected.has('ambient_correction')) {
    if (selected.has('doublet_detection')) add('ambient_correction', 'doublet_detection');
    else add('ambient_correction', 'qc_filter');
  }

  if (selected.has('normalize')) {
    if (selected.has('ambient_correction')) add('normalize', 'ambient_correction');
    else if (selected.has('doublet_detection')) add('normalize', 'doublet_detection');
    else add('normalize', 'qc_filter');
  }

  add('select_hvg', 'normalize');
  add('run_pca', 'select_hvg');

  const batchStep =
    ['batch_correct', 'batch_correction', 'batch_correction_harmony', 'batch_correction_scvi'].find(
      (name) => selected.has(name)
    ) ?? null;
  if (batchStep) add(batchStep, 'run_pca');

  const clusterParent = batchStep ?? 'run_pca';
  add('cluster', clusterParent);
  add('embed', clusterParent);
  add('umap', clusterParent);
  add('tsne', clusterParent);

  const annotationParent = selected.has('cluster') ? 'cluster' : clusterParent;
  add('annotate', annotationParent);

  const deParent = selected.has('annotate') ? 'annotate' : annotationParent;
  add('differential_expression', deParent);

  const pathwayParent = selected.has('differential_expression')
    ? 'differential_expression'
    : deParent;
  add('pathway_scoring', pathwayParent);

  const lrParent = selected.has('pathway_scoring')
    ? 'pathway_scoring'
    : selected.has('differential_expression')
      ? 'differential_expression'
      : deParent;
  add('ligand_receptor_analysis', lrParent);

  return dependencies;
}

function buildDefinition(
  catalog: PipelineMethodCatalogEntry[],
  selectedMethodNames: string[],
  parameterRows: ParameterFieldRow[],
  description: string,
  initialTemplate?: PipelineTemplate | null
): Record<string, unknown> {
  const methods: MethodEntry[] = [...catalog]
    .sort((a, b) => a.order - b.order)
    .filter((entry) => selectedMethodNames.includes(entry.name))
    .map((entry) =>
      entry.enabled_if ? { name: entry.name, enabled_if: entry.enabled_if } : entry.name
    );

  if (methods.length === 0) {
    throw new Error('At least one pipeline step must be selected.');
  }

  const initialMetadata =
    (initialTemplate?.definition?.metadata as Record<string, unknown> | undefined) ?? {};

  return {
    methods,
    dependencies: buildDependencies(methods),
    parameter_schema: buildParameterSchema(parameterRows),
    metadata: {
      ...initialMetadata,
      description: description.trim(),
    },
  };
}

function SubmitButton({ disabled }: { disabled: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={disabled || pending}
      className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {pending ? 'Saving…' : 'Save template'}
    </button>
  );
}

export default function PipelineTemplateEditor({ catalog, initialTemplate = null }: Props) {
  const [state, formAction] = useFormState(savePipelineTemplateAction, initialState);
  const [name, setName] = useState(initialTemplate?.name ?? '');
  const [version, setVersion] = useState(
    initialTemplate ? incrementVersion(initialTemplate.version) : '1.0.0'
  );
  const [description, setDescription] = useState(
    typeof (initialTemplate?.definition?.metadata as Record<string, unknown> | undefined)
      ?.description === 'string'
      ? ((initialTemplate?.definition?.metadata as Record<string, unknown> | undefined)
          ?.description as string)
      : ''
  );
  const [selectedMethodNames, setSelectedMethodNames] = useState<string[]>(
    parseMethodSelection(catalog, initialTemplate)
  );
  const [parameterRows, setParameterRows] = useState<ParameterFieldRow[]>(
    parseParameterRows(initialTemplate)
  );
  const [deactivateSource, setDeactivateSource] = useState(true);

  const orderedCatalog = useMemo(() => [...catalog].sort((a, b) => a.order - b.order), [catalog]);

  const duplicateParameterNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of parameterRows) {
      const value = row.name.trim();
      if (!value) continue;
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
    return [...counts.entries()].filter(([, count]) => count > 1).map(([key]) => key);
  }, [parameterRows]);

  const definitionResult = useMemo(() => {
    try {
      return {
        definition: buildDefinition(
          orderedCatalog,
          selectedMethodNames,
          parameterRows,
          description,
          initialTemplate
        ),
        error: null,
      };
    } catch (err: unknown) {
      return {
        definition: null,
        error: err instanceof Error ? err.message : 'Failed to build template definition.',
      };
    }
  }, [description, initialTemplate, orderedCatalog, parameterRows, selectedMethodNames]);

  const dependencyPreview = useMemo(() => {
    if (!definitionResult.definition) return {};
    return (definitionResult.definition.dependencies as Record<string, string[]>) ?? {};
  }, [definitionResult.definition]);

  const definitionJson = useMemo(
    () => (definitionResult.definition ? JSON.stringify(definitionResult.definition, null, 2) : ''),
    [definitionResult.definition]
  );

  function toggleMethod(methodName: string) {
    setSelectedMethodNames((current) =>
      current.includes(methodName)
        ? current.filter((name) => name !== methodName)
        : [...current, methodName]
    );
  }

  function updateParameterRow(id: string, patch: Partial<ParameterFieldRow>) {
    setParameterRows((current) =>
      current.map((row) => (row.id === id ? { ...row, ...patch } : row))
    );
  }

  function addParameterRow() {
    setParameterRows((current) => [
      ...current,
      {
        id: generateId(),
        name: '',
        type: 'string',
        description: '',
        defaultValue: '',
        minimum: '',
        maximum: '',
        enumValues: '',
        required: false,
      },
    ]);
  }

  function removeParameterRow(id: string) {
    setParameterRows((current) => current.filter((row) => row.id !== id));
  }

  const isCloneMode = Boolean(initialTemplate);
  const disableSubmit =
    !name.trim() ||
    !version.trim() ||
    selectedMethodNames.length === 0 ||
    duplicateParameterNames.length > 0 ||
    Boolean(definitionResult.error);

  return (
    <form action={formAction} className="space-y-8 max-w-6xl">
      {state.error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {state.error}
        </div>
      )}
      {definitionResult.error && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          {definitionResult.error}
        </div>
      )}
      {duplicateParameterNames.length > 0 && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          Duplicate parameter names: {duplicateParameterNames.join(', ')}
        </div>
      )}
      {state.fieldErrors?.definition && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {state.fieldErrors.definition}
        </div>
      )}

      <input type="hidden" name="definition" value={definitionJson} />
      {initialTemplate && (
        <input type="hidden" name="source_template_id" value={initialTemplate.id} />
      )}

      <section className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="space-y-6 rounded-xl border border-gray-200 bg-white p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
                Template name
              </label>
              <input
                id="name"
                name="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="input w-full"
                placeholder="scRNA-seq Standard"
              />
              {state.fieldErrors?.name && (
                <p className="mt-1 text-xs text-red-600">{state.fieldErrors.name}</p>
              )}
            </div>
            <div>
              <label htmlFor="version" className="mb-1 block text-sm font-medium text-gray-700">
                Version
              </label>
              <input
                id="version"
                name="version"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                className="input w-full"
                placeholder="1.1.0"
              />
              {state.fieldErrors?.version && (
                <p className="mt-1 text-xs text-red-600">{state.fieldErrors.version}</p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="description" className="mb-1 block text-sm font-medium text-gray-700">
              Description
            </label>
            <textarea
              id="description"
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="input w-full"
              placeholder="Describe when this template should be used."
            />
          </div>

          {isCloneMode && (
            <label className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
              <input
                type="checkbox"
                name="deactivate_source"
                checked={deactivateSource}
                onChange={(event) => setDeactivateSource(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600"
              />
              Deactivate the previous active version after saving this one
            </label>
          )}
        </div>

        <aside className="space-y-4 rounded-xl border border-gray-200 bg-gray-50 p-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Summary</p>
            <p className="mt-2 text-sm text-gray-700">
              {selectedMethodNames.length} steps selected,{' '}
              {parameterRows.filter((row) => row.name.trim()).length} parameters defined.
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Dependency Preview
            </p>
            <div className="mt-3 space-y-2">
              {Object.entries(dependencyPreview).length === 0 && (
                <p className="text-sm text-gray-500">
                  Dependencies will appear once steps are selected.
                </p>
              )}
              {Object.entries(dependencyPreview).map(([step, dependencies]) => (
                <div key={step} className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-sm font-medium text-gray-800">{step}</p>
                  <p className="mt-1 text-xs text-gray-500">depends on {dependencies.join(', ')}</p>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Method Picker</h2>
            <p className="text-sm text-gray-500">
              Select the steps this template should include. Optional steps can stay in the template
              and only run when their toggle parameter is enabled.
            </p>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {orderedCatalog.map((entry) => {
            const selected = selectedMethodNames.includes(entry.name);
            return (
              <button
                key={entry.name}
                type="button"
                onClick={() => toggleMethod(entry.name)}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  selected
                    ? 'border-blue-300 bg-blue-50'
                    : 'border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-white'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{entry.label}</p>
                    <p className="mt-1 text-sm text-gray-600">{entry.description}</p>
                  </div>
                  <input
                    type="checkbox"
                    readOnly
                    checked={selected}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                  />
                </div>
                {entry.enabled_if && (
                  <p className="mt-3 text-xs font-medium uppercase tracking-wide text-blue-700">
                    Optional at run time via <code>{entry.enabled_if}</code>
                  </p>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Parameter Schema</h2>
            <p className="text-sm text-gray-500">
              Define the run parameters exposed to users. Defaults are injected into the run form.
            </p>
          </div>
          <button type="button" onClick={addParameterRow} className="btn-secondary">
            Add parameter
          </button>
        </div>

        <div className="space-y-4">
          {parameterRows.map((row) => (
            <div key={row.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Name
                  </label>
                  <input
                    value={row.name}
                    onChange={(event) => updateParameterRow(row.id, { name: event.target.value })}
                    className="input w-full"
                    placeholder="batch_key"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Type
                  </label>
                  <select
                    value={row.type}
                    onChange={(event) =>
                      updateParameterRow(row.id, { type: event.target.value as ParameterType })
                    }
                    className="input w-full"
                  >
                    {PARAMETER_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Default
                  </label>
                  <input
                    value={row.defaultValue}
                    onChange={(event) =>
                      updateParameterRow(row.id, { defaultValue: event.target.value })
                    }
                    className="input w-full"
                    placeholder={row.type === 'boolean' ? 'true' : 'Optional'}
                  />
                </div>
                <div className="flex items-end gap-3">
                  <label className="flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={row.required}
                      onChange={(event) =>
                        updateParameterRow(row.id, { required: event.target.checked })
                      }
                      className="h-4 w-4 rounded border-gray-300 text-blue-600"
                    />
                    Required
                  </label>
                  <button
                    type="button"
                    onClick={() => removeParameterRow(row.id)}
                    className="text-sm font-medium text-red-600 hover:text-red-700"
                  >
                    Remove
                  </button>
                </div>
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="md:col-span-2 xl:col-span-2">
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Description
                  </label>
                  <input
                    value={row.description}
                    onChange={(event) =>
                      updateParameterRow(row.id, { description: event.target.value })
                    }
                    className="input w-full"
                    placeholder="obs column containing batch identifiers"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Minimum
                  </label>
                  <input
                    value={row.minimum}
                    onChange={(event) =>
                      updateParameterRow(row.id, { minimum: event.target.value })
                    }
                    className="input w-full"
                    placeholder="0"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Maximum
                  </label>
                  <input
                    value={row.maximum}
                    onChange={(event) =>
                      updateParameterRow(row.id, { maximum: event.target.value })
                    }
                    className="input w-full"
                    placeholder="100"
                  />
                </div>
              </div>

              <div className="mt-4">
                <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Enum Values
                </label>
                <input
                  value={row.enumValues}
                  onChange={(event) =>
                    updateParameterRow(row.id, { enumValues: event.target.value })
                  }
                  className="input w-full"
                  placeholder={
                    row.type === 'array' || row.type === 'object'
                      ? '["harmony", "scvi"]'
                      : 'value_a, value_b'
                  }
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">Definition Preview</h2>
        <p className="mt-1 text-sm text-gray-500">
          This JSON is what will be saved as the pipeline definition.
        </p>
        <pre className="mt-4 max-h-[28rem] overflow-auto rounded-xl bg-gray-950 p-4 text-xs text-gray-100">
          {definitionJson || '// Invalid definition'}
        </pre>
      </section>

      <div className="flex gap-3">
        <SubmitButton disabled={disableSubmit} />
        <a href="/pipelines" className="btn-secondary">
          Cancel
        </a>
      </div>
    </form>
  );
}

function incrementVersion(version: string): string {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) return version;
  const [, major, minor, patch] = match;
  return `${major}.${minor}.${Number.parseInt(patch, 10) + 1}`;
}
