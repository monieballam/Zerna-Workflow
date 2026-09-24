'use client';

import { useCallback, useEffect, useRef, useState, type InputHTMLAttributes } from 'react';
import { uploadFileStableKey } from '@/lib/upload-file-stable-key';

const ACCEPTED = '.h5ad,.h5,.mtx,.csv,.tsv,.gz,.txt';
const ACCEPTED_EXTS = new Set(['.h5ad', '.h5', '.mtx', '.csv', '.tsv', '.gz', '.txt']);

interface Props {
  error?: string;
  /** Fires when the ordered file list changes (names only, for multi-sample label hints). */
  onSelectionChange?: (fileNames: string[]) => void;
  /** Controlled mode: parent owns files (e.g. multi-dataset upload). Omit for uncontrolled + form field `files`. */
  value?: File[];
  onChange?: (files: File[]) => void;
  /** When the parent renders its own per-file list (e.g. metadata cards), hide the built-in file list. */
  hideFileList?: boolean;
}

function ext(name: string): string {
  return name.slice(name.lastIndexOf('.')).toLowerCase();
}

export default function FileDropZone({
  error,
  onSelectionChange,
  value,
  onChange,
  hideFileList = false,
}: Props) {
  const controlled = value !== undefined;
  const inputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);
  const [internalFiles, setInternalFiles] = useState<File[]>([]);
  const files = controlled ? value! : internalFiles;

  const setFiles = useCallback(
    (next: File[] | ((prev: File[]) => File[])) => {
      if (controlled) {
        const base = value!;
        const resolved = typeof next === 'function' ? next(base) : next;
        onChange?.(resolved);
      } else {
        setInternalFiles((prev) => (typeof next === 'function' ? next(prev) : next));
      }
    },
    [controlled, value, onChange]
  );

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      const valid = Array.from(incoming).filter((f) => ACCEPTED_EXTS.has(ext(f.name)));
      setFiles((prev) => {
        const keys = new Set(prev.map((f) => uploadFileStableKey(f)));
        return [...prev, ...valid.filter((f) => !keys.has(uploadFileStableKey(f)))];
      });
    },
    [setFiles]
  );

  const removeFile = (key: string) =>
    setFiles((prev) => prev.filter((f) => uploadFileStableKey(f) !== key));

  const [dragging, setDragging] = useState(false);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const syncRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (controlled) return;
    if (!syncRef.current) return;
    if (typeof DataTransfer === 'undefined') return;
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    syncRef.current.files = dt.files;
  }, [controlled, files]);

  useEffect(() => {
    onSelectionChange?.(files.map((f) => f.name));
  }, [files, onSelectionChange]);

  return (
    <div>
      {!controlled && (
        <input
          ref={syncRef}
          type="file"
          name="files"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
        />
      )}

      <div
        role="button"
        tabIndex={0}
        aria-label="Drop files here or click to browse"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragging
            ? 'border-blue-500 bg-blue-50'
            : error
              ? 'border-red-400 bg-red-50'
              : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'
        }`}
      >
        <svg
          className="mx-auto h-10 w-10 text-gray-400 mb-3"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
          />
        </svg>
        <p className="text-sm text-gray-600">
          <span className="font-medium text-blue-600">Click to browse</span> or drag and drop
        </p>
        <p className="text-xs text-gray-400 mt-1">
          Supported: .h5ad, .h5, .mtx, .csv, .tsv, .gz, .txt
        </p>
        <p className="mt-3 flex flex-wrap items-center justify-center gap-2 text-xs text-gray-500">
          <button
            type="button"
            className="rounded-md border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700 hover:bg-gray-50"
            onClick={(e) => {
              e.stopPropagation();
              dirInputRef.current?.click();
            }}
          >
            Add folder…
          </button>
          <span className="text-gray-400">(GEO-style: one sample per subfolder)</span>
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED}
        className="sr-only"
        onChange={(e) => addFiles(e.target.files)}
        aria-label="File input"
      />
      <input
        ref={dirInputRef}
        type="file"
        multiple
        className="sr-only"
        {...({ webkitdirectory: '' } as InputHTMLAttributes<HTMLInputElement>)}
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = '';
        }}
        aria-label="Folder input"
      />

      {error && <p className="mt-1 text-sm text-red-600">{error}</p>}

      {files.length > 0 && !hideFileList && (
        <ul className="mt-3 space-y-1" aria-label="Selected files">
          {files.map((f) => {
            const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
            const key = uploadFileStableKey(f);
            return (
              <li
                key={key}
                className="flex items-center justify-between rounded bg-gray-50 px-3 py-2 text-sm"
              >
                <span className="min-w-0 truncate text-gray-700 font-mono" title={rel || f.name}>
                  {rel || f.name}
                </span>
                <span className="ml-3 text-gray-400 shrink-0">{formatSize(f.size)}</span>
                <button
                  type="button"
                  onClick={() => removeFile(key)}
                  className="ml-3 text-gray-400 hover:text-red-500 transition-colors shrink-0"
                  aria-label={`Remove ${rel || f.name}`}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
