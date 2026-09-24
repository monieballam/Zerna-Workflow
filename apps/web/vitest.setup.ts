import '@testing-library/jest-dom';
import { vi } from 'vitest';

function createLocalStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.get(key) ?? null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
  };
}

function hasUsableLocalStorage(storage: Storage | undefined): storage is Storage {
  return (
    typeof storage?.getItem === 'function' &&
    typeof storage.setItem === 'function' &&
    typeof storage.removeItem === 'function'
  );
}

let activeLocalStorage: Storage | undefined;
try {
  activeLocalStorage = window.localStorage;
} catch {
  activeLocalStorage = undefined;
}

if (!hasUsableLocalStorage(activeLocalStorage)) {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: createLocalStorageMock(),
  });
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}

if (typeof HTMLCanvasElement !== 'undefined') {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () => ({}) as RenderingContext
  );
}
