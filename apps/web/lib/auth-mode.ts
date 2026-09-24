/** Local/dev flag: skip login UI and accept unauthenticated API access. */
export function isAuthDisabled(): boolean {
  const value =
    process.env.AUTH_DISABLED ?? process.env.NEXT_PUBLIC_AUTH_DISABLED ?? '';
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}
