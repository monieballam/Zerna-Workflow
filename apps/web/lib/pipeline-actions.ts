'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { createServerClient } from './api';

export interface SavePipelineTemplateState {
  error?: string;
  fieldErrors?: Record<string, string>;
}

export async function savePipelineTemplateAction(
  _prevState: SavePipelineTemplateState,
  formData: FormData
): Promise<SavePipelineTemplateState> {
  const name = (formData.get('name') as string | null)?.trim();
  const version = (formData.get('version') as string | null)?.trim();
  const definitionRaw = (formData.get('definition') as string | null)?.trim();
  const sourceTemplateId = (formData.get('source_template_id') as string | null)?.trim();
  const deactivateSource = formData.get('deactivate_source') === 'on';

  const fieldErrors: Record<string, string> = {};
  if (!name) fieldErrors.name = 'Template name is required.';
  if (!version) fieldErrors.version = 'Version is required.';
  if (!definitionRaw) fieldErrors.definition = 'Template definition is required.';

  let definition: Record<string, unknown> | null = null;
  if (definitionRaw) {
    try {
      definition = JSON.parse(definitionRaw) as Record<string, unknown>;
    } catch {
      fieldErrors.definition = 'Template definition must be valid JSON.';
    }
  }

  if (Object.keys(fieldErrors).length > 0) {
    return { fieldErrors };
  }

  try {
    const client = createServerClient();
    if (sourceTemplateId) {
      await client.pipelines.clone(sourceTemplateId, {
        name: name!,
        version: version!,
        definition: definition ?? undefined,
        deactivate_source: deactivateSource,
      });
    } else {
      await client.pipelines.create({
        name: name!,
        version: version!,
        definition: definition ?? {},
      });
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to save pipeline template.';
    return { error: message };
  }

  revalidatePath('/pipelines');
  revalidatePath('/runs/new');
  redirect('/pipelines');
}

export async function syncDefaultTemplatesAction(): Promise<void> {
  try {
    const client = createServerClient();
    await client.pipelines.syncDefaults();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to sync default templates.';
    redirect(`/pipelines?error=${encodeURIComponent(message)}`);
  }

  revalidatePath('/pipelines');
  revalidatePath('/runs/new');
  redirect('/pipelines');
}

export async function deactivatePipelineTemplateAction(templateId: string): Promise<void> {
  try {
    const client = createServerClient();
    await client.pipelines.deactivate(templateId);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Failed to deactivate template.';
    redirect(`/pipelines?error=${encodeURIComponent(message)}`);
  }

  revalidatePath('/pipelines');
  revalidatePath('/runs/new');
  redirect('/pipelines');
}
