/**
 * Register the service worker for offline support.
 * Call this once from the root layout or a client component.
 */
export function registerServiceWorker(): void {
  if (
    typeof window === 'undefined' ||
    !('serviceWorker' in navigator) ||
    process.env.NODE_ENV === 'development'
  ) {
    return;
  }

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        console.log('SW registered:', registration.scope);
      })
      .catch((err) => {
        console.warn('SW registration failed:', err);
      });
  });
}
