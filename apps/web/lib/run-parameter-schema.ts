import type { PipelineTemplate } from '@zerna/sdk';

export type TemplateParameterSpec = Record<string, unknown>;
export type TemplateParameterSchema = {
  properties?: Record<string, TemplateParameterSpec>;
  required?: string[];
  allOf?: unknown[];
};

export type ConditionalForcedValue = {
  value: unknown;
  reason?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function getParameterSchemaFromTemplate(
  template?: PipelineTemplate | null
): TemplateParameterSchema | null {
  const schema = template?.definition?.parameter_schema as TemplateParameterSchema | undefined;
  return schema ?? null;
}

function matchesSchemaCondition(
  ifSchema: Record<string, unknown>,
  values: Record<string, unknown>
): boolean {
  const required = ifSchema.required;
  if (Array.isArray(required)) {
    for (const fieldName of required) {
      if (typeof fieldName !== 'string') {
        return false;
      }
      if (!isParameterValueProvided(values[fieldName])) {
        return false;
      }
    }
  }

  const properties = ifSchema.properties;
  if (!isRecord(properties)) {
    return false;
  }

  for (const [paramName, rawSpec] of Object.entries(properties)) {
    if (!isRecord(rawSpec)) {
      return false;
    }

    const constValue = rawSpec.const;
    if (constValue !== undefined && values[paramName] !== constValue) {
      return false;
    }
  }

  return true;
}

function applyConditionalConstsOnce(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): { values: Record<string, unknown>; changed: boolean } {
  const next = { ...values };
  let changed = false;

  for (const rule of schema?.allOf ?? []) {
    if (!isRecord(rule)) {
      continue;
    }

    const ifSchema = rule.if;
    const thenSchema = rule.then;
    if (!isRecord(ifSchema) || !isRecord(thenSchema)) {
      continue;
    }

    if (!matchesSchemaCondition(ifSchema, next)) {
      continue;
    }

    const thenProperties = thenSchema.properties;
    if (!isRecord(thenProperties)) {
      continue;
    }

    for (const [fieldName, rawSpec] of Object.entries(thenProperties)) {
      if (!isRecord(rawSpec) || !Object.prototype.hasOwnProperty.call(rawSpec, 'const')) {
        continue;
      }
      const forcedValue = rawSpec.const;
      if (next[fieldName] !== forcedValue) {
        next[fieldName] = forcedValue;
        changed = true;
      }
    }
  }

  return { values: next, changed };
}

function getConstrainedValues(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): Record<string, unknown> {
  let constrained = { ...values };

  for (let iteration = 0; iteration < 8; iteration += 1) {
    const result = applyConditionalConstsOnce(schema, constrained);
    constrained = result.values;
    if (!result.changed) {
      break;
    }
  }

  return constrained;
}

export function applyConditionalParameterConstraints(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): Record<string, unknown> {
  return getConstrainedValues(schema, values);
}

export function getConditionalForcedValues(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): Record<string, ConditionalForcedValue> {
  const constrained = getConstrainedValues(schema, values);
  const forced: Record<string, ConditionalForcedValue> = {};

  for (const rule of schema?.allOf ?? []) {
    if (!isRecord(rule)) {
      continue;
    }

    const ifSchema = rule.if;
    const thenSchema = rule.then;
    if (!isRecord(ifSchema) || !isRecord(thenSchema)) {
      continue;
    }

    if (!matchesSchemaCondition(ifSchema, constrained)) {
      continue;
    }

    const thenProperties = thenSchema.properties;
    if (!isRecord(thenProperties)) {
      continue;
    }

    for (const [fieldName, rawSpec] of Object.entries(thenProperties)) {
      if (!isRecord(rawSpec) || !Object.prototype.hasOwnProperty.call(rawSpec, 'const')) {
        continue;
      }
      forced[fieldName] = {
        value: rawSpec.const,
        reason:
          typeof rawSpec['x-zerna-lock-reason'] === 'string'
            ? rawSpec['x-zerna-lock-reason']
            : undefined,
      };
    }
  }

  return forced;
}

export function getEffectiveRequiredFields(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): Set<string> {
  const constrainedValues = getConstrainedValues(schema, values);
  const required = new Set(schema?.required ?? []);

  for (const rule of schema?.allOf ?? []) {
    if (!isRecord(rule)) {
      continue;
    }

    const ifSchema = rule.if;
    const thenSchema = rule.then;
    if (!isRecord(ifSchema) || !isRecord(thenSchema)) {
      continue;
    }

    if (!matchesSchemaCondition(ifSchema, constrainedValues)) {
      continue;
    }

    const conditionalRequired = thenSchema.required;
    if (!Array.isArray(conditionalRequired)) {
      continue;
    }

    for (const fieldName of conditionalRequired) {
      if (typeof fieldName === 'string' && fieldName.trim()) {
        required.add(fieldName);
      }
    }
  }

  return required;
}

export function isParameterValueProvided(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  return true;
}

export function buildRequiredParameterErrors(
  schema: TemplateParameterSchema | null,
  values: Record<string, unknown>
): Record<string, string> {
  const constrainedValues = getConstrainedValues(schema, values);
  const requiredFields = getEffectiveRequiredFields(schema, constrainedValues);
  const errors: Record<string, string> = {};

  for (const fieldName of requiredFields) {
    if (!isParameterValueProvided(constrainedValues[fieldName])) {
      errors[fieldName] = 'Required for this run.';
    }
  }

  return errors;
}

export function extractParameterNameFromValidationMessage(message?: string | null): string | null {
  if (!message) return null;

  const patterns = [/required parameter '([^']+)'/i, /parameter '([^']+)'/i];
  for (const pattern of patterns) {
    const match = message.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }

  return null;
}
