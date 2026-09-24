'use server';

import type { ZernaClient } from '@zerna/sdk';
import { redirect } from 'next/navigation';
import { getAuthenticatedApiClientForServerAction } from './server-auth-session';
import {
  buildRequiredParameterErrors,
  extractParameterNameFromValidationMessage,
  getParameterSchemaFromTemplate,
} from './run-parameter-schema';

export interface CreateRunState {
  error?: string;
  fieldErrors?: Record<string, string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

type ParsedRunForm = {
  datasetVersionId: string | null;
  templateId: string | null;
  randomSeed: number | undefined;
  parameters: Record<string, unknown>;
  fieldErrors: Record<string, string>;
};

function parseRunFormData(formData: FormData): ParsedRunForm {
  const datasetVersionId = (formData.get('dataset_version_id') as string | null)?.trim() ?? null;
  const templateId = (formData.get('template_id') as string | null)?.trim() ?? null;
  const randomSeedRaw = formData.get('random_seed') as string | null;
  const parametersRaw = formData.get('parameters') as string | null;

  const fieldErrors: Record<string, string> = {};
  if (!datasetVersionId) fieldErrors.dataset_version_id = 'Dataset version is required.';
  if (!templateId) fieldErrors.template_id = 'Pipeline template is required.';

  let parameters: Record<string, unknown> = {};
  if (parametersRaw) {
    try {
      const parsed = JSON.parse(parametersRaw) as unknown;
      if (!isRecord(parsed)) {
        throw new Error('Parameters must decode to an object.');
      }
      parameters = parsed;
    } catch {
      fieldErrors.parameters = 'Parameters must be valid JSON.';
    }
  }

  return {
    datasetVersionId,
    templateId,
    randomSeed: randomSeedRaw ? parseInt(randomSeedRaw, 10) : undefined,
    parameters,
    fieldErrors,
  };
}

async function validateRunForm(
  client: ZernaClient,
  templateId: string,
  parameters: Record<string, unknown>,
  fieldErrors: Record<string, string>
): Promise<Record<string, string>> {
  const template = await client.pipelines.get(templateId);
  const parameterSchema = getParameterSchemaFromTemplate(template);

  Object.assign(fieldErrors, buildRequiredParameterErrors(parameterSchema, parameters));

  if (Object.keys(fieldErrors).length === 0) {
    const validation = await client.pipelines.validateParameters(templateId, { parameters });
    if (!validation.valid) {
      const parameterName = extractParameterNameFromValidationMessage(validation.error);
      if (parameterName) {
        fieldErrors[parameterName] = validation.error ?? 'Invalid parameter value.';
      } else {
        fieldErrors.parameters = validation.error ?? 'Parameters are invalid.';
      }
    }
  }

  return fieldErrors;
}

export async function createRunAction(
  _prevState: CreateRunState,
  formData: FormData
): Promise<CreateRunState> {
  const { datasetVersionId, templateId, randomSeed, parameters, fieldErrors } =
    parseRunFormData(formData);

  if (Object.keys(fieldErrors).length > 0) return { fieldErrors };

  let runId: string;
  try {
    const session = await getAuthenticatedApiClientForServerAction();
    if ('error' in session) {
      return { error: session.error };
    }
    const client = session.client;
    await validateRunForm(client, templateId!, parameters, fieldErrors);

    if (Object.keys(fieldErrors).length > 0) {
      return { fieldErrors };
    }

    const run = await client.runs.create({
      dataset_version_id: datasetVersionId!,
      template_id: templateId!,
      parameters,
      random_seed: randomSeed,
    });
    runId = run.id;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to create run.';
    const parameterName = extractParameterNameFromValidationMessage(message);
    if (parameterName) {
      return { fieldErrors: { [parameterName]: message } };
    }
    return { error: message };
  }

  redirect(`/runs/${runId}`);
}

export async function resumeRunAction(
  _prevState: CreateRunState,
  formData: FormData
): Promise<CreateRunState> {
  const runId = (formData.get('run_id') as string | null)?.trim();
  if (!runId) {
    return { error: 'Run ID is required to resume a failed run.' };
  }

  const { templateId, randomSeed, parameters, fieldErrors } = parseRunFormData(formData);
  if (Object.keys(fieldErrors).length > 0) return { fieldErrors };

  try {
    const session = await getAuthenticatedApiClientForServerAction();
    if ('error' in session) {
      return { error: session.error };
    }
    const client = session.client;
    await validateRunForm(client, templateId!, parameters, fieldErrors);

    if (Object.keys(fieldErrors).length > 0) {
      return { fieldErrors };
    }

    await client.runs.resume(runId, {
      parameters,
      random_seed: randomSeed,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to resume run.';
    const parameterName = extractParameterNameFromValidationMessage(message);
    if (parameterName) {
      return { fieldErrors: { [parameterName]: message } };
    }
    return { error: message };
  }

  redirect(`/runs/${runId}`);
}

export async function cancelRunAction(runId: string): Promise<{ error?: string }> {
  const session = await getAuthenticatedApiClientForServerAction();
  if ('error' in session) {
    return { error: session.error };
  }
  try {
    await session.client.runs.cancel(runId);
    return {};
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to cancel run.';
    if (message.includes('401')) {
      return {
        error:
          'Your session expired while this page was open. Refresh the page or log in again, then try Cancel.',
      };
    }
    return { error: message };
  }
}
