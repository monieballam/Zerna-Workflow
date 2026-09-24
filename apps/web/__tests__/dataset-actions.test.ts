import { beforeEach, describe, expect, it, vi } from 'vitest';

const { redirectMock, createDatasetMock, createVersionMock, getAuthTokenMock, sessionMock } =
  vi.hoisted(() => ({
    redirectMock: vi.fn(),
    createDatasetMock: vi.fn(),
    createVersionMock: vi.fn(),
    getAuthTokenMock: vi.fn(),
    sessionMock: vi.fn(),
  }));

vi.mock('next/navigation', () => ({
  redirect: redirectMock,
}));

vi.mock('@/lib/server-auth-session', () => ({
  getAuthenticatedApiClientForServerAction: sessionMock,
}));

vi.mock('@/lib/auth', () => ({
  getAuthToken: getAuthTokenMock,
}));

import { uploadDatasetAction } from '@/lib/dataset-actions';

describe('uploadDatasetAction', () => {
  beforeEach(() => {
    redirectMock.mockReset();
    createDatasetMock.mockReset();
    createVersionMock.mockReset();
    getAuthTokenMock.mockReset();
    sessionMock.mockReset();
    createDatasetMock.mockResolvedValue({ id: 'ds-1' });
    createVersionMock.mockResolvedValue({ id: 'v-1' });
    getAuthTokenMock.mockReturnValue(undefined);
    sessionMock.mockResolvedValue({
      client: {
        datasets: {
          create: createDatasetMock,
          createVersion: createVersionMock,
        },
      },
    });
  });

  it('creates the dataset first and uploads files as a dataset version', async () => {
    const form = new FormData();
    form.set('name', 'PBMC upload');
    form.set('description', 'Upload repro');
    form.append(
      'files',
      new File(['a\tb\n1\t2\n'], 'small.tsv', { type: 'text/tab-separated-values' })
    );
    form.set(
      'file_upload_manifest',
      JSON.stringify([
        {
          dataset_name: 'small',
          condition: '',
          file_names: ['small.tsv'],
        },
      ])
    );

    await uploadDatasetAction({}, form);

    expect(createDatasetMock).toHaveBeenCalledWith({
      name: 'PBMC upload',
      description: 'Upload repro',
      metadata: {
        per_file_upload_metadata: [
          {
            dataset_name: 'small',
            condition: '',
            file_names: ['small.tsv'],
          },
        ],
        expression_dataset_names: ['small'],
        expression_sample_conditions: ['small'],
        expression_sample_labels: ['small'],
      },
    });
    expect(createVersionMock).toHaveBeenCalledTimes(1);
    const [datasetIdArg, filesArg] = createVersionMock.mock.calls[0] as [string, File[]];
    expect(datasetIdArg).toBe('ds-1');
    expect(filesArg).toHaveLength(1);
    expect(filesArg[0].name).toBe('small.tsv');
    expect(redirectMock).toHaveBeenCalledWith('/datasets');
  });
});
