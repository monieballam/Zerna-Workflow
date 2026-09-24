/** Stable identity for upload list deduplication and duplicate detection. */
export function uploadFileStableKey(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (rel && typeof rel === 'string' && rel.length > 0) {
    return rel;
  }
  return `${file.name}\0${file.size}`;
}
